# Chaos Mesh for Online Boutique

Chaos Mesh injects failures and resource pressure into running pods. Use request traffic alongside the experiments to measure how the application behaves. This setup combines Chaos Mesh with the demo's existing Locust shopping flows; it does not implement the future autonomous testing agent yet.

## Install

Run from your normal host terminal:

```bash
cd /home/aashrith/Desktop/boschthon
bash scripts/install-chaos.sh
```

The installer downloads checksum-verified Helm v3.19.0 into `.runtime/tools/helm`, installs Chaos Mesh chart 2.8.4 in namespace `chaos-mesh`, waits for its workloads, and validates the experiment manifests using a server dry run. It does not start experiments. It uses your project kubeconfig and explicitly selects `kind-online-boutique`.

The daemon talks to **containerd inside the kind node** at `/run/containerd/containerd.sock`. Podman runs the outer kind container. Namespace filtering is enabled, and only `online-boutique` is annotated to allow injection. There is one controller replica to suit the local cluster. DNS chaos is not enabled.

For network experiments, load the host's legacy iptables, ipset, and netem kernel modules. Fedora can have nftables loaded while the legacy tables used by the Chaos Mesh daemon are absent:

```bash
sudo modprobe -a ip_tables iptable_filter iptable_mangle ip_set ip_set_hash_ip xt_set sch_netem
```

If that reports the module is missing, install the matching Fedora kernel modules package or boot a kernel with netem support. A working dashboard or ready daemon does not prove that every fault type works under rootless Podman; check each experiment's injection status. Network and stress injection may encounter namespace or cgroup permission limitations.

If an experiment reports `unable to set ip tables chains`, inspect the daemon's underlying error with `kubectl --context kind-online-boutique -n chaos-mesh logs daemonset/chaos-daemon --since=10m --tail=200`. Missing tables and permission failures require different fixes. After loading missing modules, delete the failed experiment and create it again. If deletion hangs, keep the daemon running and inspect its logs; do not force-remove cleanup finalizers.

## Dashboard

```bash
bash scripts/chaos.sh dashboard
```

Open **http://localhost:2333**, keeping the terminal running. The dashboard uses a ClusterIP service and a localhost-only port-forward. Authentication is disabled for this local development setup. It is not configured for public access. Closing the port-forward does not stop an experiment.

Use **New Experiment**, choose Pod Fault / Network Attack / Stress Test, select namespace `online-boutique`, and set a label selector such as `app=shippingservice`. Start with `mode: one` and a 30–60 second duration for continuous faults. Pod Kill is a one-time deletion; Kubernetes recreates the pod. The dashboard also displays experiment status and events. The supplied YAML manifests give reproducible configurations that the future agent can use directly.

## Start request traffic

```bash
export KUBECONFIG="$PWD/.runtime/kubeconfig"
bash scripts/load.sh start 20 2
bash scripts/load.sh logs
```

`USERS` is concurrent simulated shoppers. `RATE` is new shoppers started per second, rather than requests per second. The Locust tasks browse products, add items, view carts, and perform mock checkouts. Its periodic statistics include request failures and response times. Keep the load at 20 users initially, then try 50 or 100 while observing resource contention; changing the environment restarts the load generator and resets its statistics.

The first start can take several minutes to pull images. Locust's main container starts only after the `frontend-check` init container succeeds. The helper waits for rollout readiness before suggesting logs; if it fails, it prints pod descriptions and init-container logs. Run `bash scripts/load.sh status` to inspect startup again, or `bash scripts/load.sh stop` to stop traffic.

The `start` helper also enables explicit periodic console statistics and CSV reports in a writable `/stats` volume. To verify actual traffic, sample counters every 5 seconds for 30 seconds:

```bash
bash scripts/load.sh measure 5 30
bash scripts/load.sh export
```

The table shows actual active users from Locust's history, cumulative completed requests and failures, interval requests per second computed from counter differences, and cumulative p95 latency in milliseconds. A rising total request count proves requests are completing; also check failures because the count includes failed requests. Snapshots are saved in `.runtime/load-reports/`. The export command saves CSV files before a restart replaces the pod's ephemeral statistics volume.

To compare low and higher request load, capture the 20-user run, then repeat with more shoppers:

```bash
bash scripts/load.sh start 100 10
bash scripts/load.sh measure 5 30
bash scripts/load.sh export
```

Wait until the `USERS` column reaches the target before comparing stable intervals. Raising users can increase RPS until the application or load generator saturates. Shipping delay does not itself increase user count or request rate; it can increase response time and reduce achieved RPS. The upstream user behavior waits 1–10 seconds between tasks, so 20 shoppers can produce only a few requests per second. Each new rollout resets counters, so compare rates rather than total counts across runs. There is no CPU metrics collection in this setup yet.

First record a baseline for 60 seconds without faults. In a second terminal, start one chaos experiment while the traffic continues. Compare request failures, latency percentiles, and recovery after the experiment ends. The experiment does not automatically determine whether the application's behavior passes a resilience requirement.

## Available experiments

| Name | Effect | Duration | What to observe |
| --- | --- | --- | --- |
| `shipping-kill` | Deletes one shipping pod; Deployment recreates it | One deletion | Cart/checkout errors during recovery and time until the replacement is ready |
| `shipping-delay` | Adds 250 ms delay with 50 ms jitter to one shipping pod's outgoing traffic | 60 seconds | Shipping quote latency in cart and checkout |
| `currency-cpu` | One CPU stress worker at load 80 in a currency container | 60 seconds | Browse latency, request errors, and CPU throttling |
| `checkout-partition` | Blocks traffic both ways between one frontend pod and checkout pods | 45 seconds | Checkout failures and recovery after connectivity returns |

The currency service has an upstream CPU limit of 200 millicores. The stress worker's load setting does not guarantee 80% utilization of your host CPU; its work competes within the container's cgroup limit. Each service starts with one replica, so killing its only pod can cause visible downtime.

Example:

```bash
bash scripts/chaos.sh start shipping-delay
bash scripts/chaos.sh show shipping-delay
bash scripts/chaos.sh status
```

The `show` command prints the resource's YAML, conditions, and events. Check `AllInjected` and experiment records/errors; a successful `kubectl create` only confirms that Kubernetes accepted the request. A failed injection is an infrastructure failure, not evidence that the application tolerated the fault.

You can also apply a manifest directly:

```bash
kubectl --context kind-online-boutique create -f chaos/experiments/shipping-delay.yaml
kubectl --context kind-online-boutique -n online-boutique describe networkchaos shipping-delay
```

Experiment objects remain after their duration finishes. Delete the old object before rerunning it:

```bash
bash scripts/chaos.sh stop shipping-delay
bash scripts/chaos.sh start shipping-delay
```

Deleting a NetworkChaos or StressChaos object requests recovery through the controller. Deleting a Pod Kill experiment cannot resurrect the deleted pod; its Deployment manages replacement. Wait for the application to recover before starting another experiment.

## Stop and recover

Stop all experiments supplied by this project and stop request traffic:

```bash
bash scripts/chaos.sh stop-all
kubectl --context kind-online-boutique -n online-boutique scale deployment/loadgenerator --replicas=0
kubectl --context kind-online-boutique -n online-boutique get pods
curl --fail http://127.0.0.1:8080/cart
```

`stop-all` selects resources with label `app.kubernetes.io/part-of=boutique-chaos`. Experiments created independently in the dashboard need to be deleted there or by name with kubectl. Continuous faults have an automatic duration, but recovery still requires a working controller and daemon. If deletion hangs, inspect controller and daemon logs rather than removing finalizers: finalizers are used to clean up injected faults.

## Diagnose installation or injection failures

```bash
export KUBECONFIG="$PWD/.runtime/kubeconfig"
kubectl --context kind-online-boutique -n chaos-mesh get pods -o wide
kubectl --context kind-online-boutique -n chaos-mesh get events --sort-by=.metadata.creationTimestamp
kubectl --context kind-online-boutique -n chaos-mesh logs deployment/chaos-controller-manager --tail=100
kubectl --context kind-online-boutique -n chaos-mesh logs daemonset/chaos-daemon --tail=100
```

The initial install pulls images from `ghcr.io`, in addition to fetching the Helm chart. Keep the pods' detailed errors when reporting download, permission, or injection failures. This repository's environment cannot reach your cluster, so installation and injection must be confirmed from the host terminal. Compatibility with this cluster's Kubernetes v1.37 and rootless runtime has not been verified here.

## Remove Chaos Mesh

Delete active experiments while the controller is still running, then uninstall:

```bash
bash scripts/chaos.sh stop-all
# Also delete any experiments you created separately in the dashboard.
.runtime/tools/helm --kubeconfig "$PWD/.runtime/kubeconfig" --kube-context kind-online-boutique uninstall chaos-mesh -n chaos-mesh
kubectl --context kind-online-boutique annotate namespace online-boutique chaos-mesh.org/inject-
```

Helm leaves the cluster-wide Chaos Mesh CRDs installed. Retaining them is fine for reinstalling; deleting a CRD deletes every resource of that type.

## Official references

- [Helm installation and container runtime settings](https://chaos-mesh.org/docs/production-installation-using-helm/)
- [Pod faults](https://chaos-mesh.org/docs/simulate-pod-chaos-on-kubernetes/)
- [Network faults and netem requirements](https://chaos-mesh.org/docs/simulate-network-chaos-on-kubernetes/)
- [CPU and memory stress](https://chaos-mesh.org/docs/simulate-heavy-stress-on-kubernetes/)
