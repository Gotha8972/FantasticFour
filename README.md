# FantasticFour — Chaos Engineering & Resilience Testing for Online Boutique

A chaos testing and resilience verification platform for the microservices-based **Google Online Boutique**, featuring automated customer journey simulation, real-time Prometheus metric tracking, Chaos Mesh fault injection, and guardrails.

---

## 📑 Table of Contents

- [Overview](#overview)
- [Dependency Map](#️-dependency-map)
- [Architecture & Components](#architecture--components)
- [Customer Simulator (`customer_simulator.py`)](#customer-simulator-customer_simulatorpy)
  - [Features](#features)
  - [Customer Journey Flow](#customer-journey-flow)
  - [Installation & Setup](#installation--setup)
  - [Usage & Execution Modes](#usage--execution-modes)
  - [Command-Line Options](#command-line-options)
  - [Prometheus Metrics Reference](#prometheus-metrics-reference)
  - [Error Tracking & Diagnostics](#error-tracking--diagnostics)
- [Chaos Engineering Workflow](#chaos-engineering-workflow)
- [Quickstart Guide](#quickstart-guide)

---

## 🌐 Overview

This repository provides tools for testing the resilience of the **Google Online Boutique** microservices demo running on Kubernetes (Kind). It includes:
1. **Realistic Customer Simulator**: Simulates multi-step e-commerce user journeys with realistic random browsing, cart manipulation, and checkout.
2. **Prometheus Metrics Exporter**: Emits live metrics on requests, latencies, checkout successes/failures, and active sessions.
3. **Deep Error Diagnostics**: Captures detailed HTTP failure paths, status codes, error bodies, and network exceptions to pinpoint broken services during chaos experiments.
4. **Chaos Injection & Safeguards**: Automated fault injection (latency, pod kill) with threshold monitoring and automatic kill-switch guards.

---

## 🗺️ Dependency Map

![Online Boutique dependency graph](docs/dependency-graph.webp)

Based on Google's architecture diagram. We **checked it against the deployment manifest** by extracting every `*_ADDR` environment variable (each one is a service-to-service call). All 17 edges in the diagram match:

| Caller | Calls |
| :--- | :--- |
| loadgenerator | frontend |
| frontend | ad, recommendation, productcatalog, cart, shipping, currency, checkout |
| checkout | productcatalog, cart, shipping, currency, payment, email |
| recommendation | productcatalog |
| cart | redis-cart |

**Manual correction:** the upstream `main` manifest also gives `frontend` a `SHOPPING_ASSISTANT_SERVICE_ADDR` (an optional AI assistant service). It isn't in the diagram and isn't part of our deployed release, so it's excluded.

**What the map tells us before any testing:**
- `productcatalog` has the most callers (3), so it's the widest blast radius.
- `checkout` depends on 6 services, so it's the most fragile path.
- `redis-cart` is a single store behind `cart`. Confirmed data loss on restart, see [KILLSWITCH_RESULTS.md](KILLSWITCH_RESULTS.md).
- `ad` and `recommendation` are optional. Confirmed: `ad` down caused 0 user-facing errors.

---

## 🛒 Customer Simulator (`customer_simulator.py`)

The simulator generates synthetic customer traffic mimicking real user behavior across the Online Boutique frontend.

### ✨ Features

- **End-to-End E-Commerce Flow**: Simulates genuine customer behavior from browsing to checkout.
- **Configurable Traffic**: Adjust number of customers, action delay, cart size, and loop intervals.
- **Prometheus Metrics Server**: Serves standard Prometheus metrics on port `9091` (`/metrics`).
- **Comprehensive Error Tracing**: Logs every HTTP error with endpoint path, status code, customer ID, and HTML/JSON response snippet.
- **Execution Modes**: Run for a bounded test duration or indefinitely in a continuous loop.

---

### 🚶 Customer Journey Flow

Each simulated customer executes a 6-step journey:

```
[1. Home Page (/)]
       │
       ▼
[2. Change Currency (/setCurrency)]
       │
       ▼
[3. Browse 1-3 Random Products (/product/{id})]
       │
       ▼
[4. Add 1-5 Items to Cart (/cart)]
       │
       ▼
[5. View Cart (/cart)]
       │
       ▼
[6. Checkout (/cart/checkout)]
```

---

### 📦 Installation & Setup

#### Prerequisites
- Python 3.10+
- Access to Online Boutique frontend (e.g., `http://localhost:8080`)

#### 1. Setup Virtual Environment & Dependencies
```bash
# Clone the repository
git clone https://github.com/Gotha8972/FantasticFour.git
cd FantasticFour

# Create and activate virtual environment
python -m venv venv

# Windows (PowerShell):
.\venv\Scripts\Activate.ps1

# Linux / macOS:
source venv/bin/activate

# Install required packages
pip install requests prometheus_client
```

---

### 🚀 Usage & Execution Modes

#### 1. Default Run (10 Customers, ~30–60 Seconds)
Simulates 10 customer journeys sequentially, prints a complete summary, and exits:
```bash
python customer_simulator.py
```

#### 2. Continuous Run (Runs Indefinitely)
Continuously generates customer traffic in loops until stopped (`Ctrl + C`). Ideal during active chaos injection:
```bash
python customer_simulator.py --loop
```

#### 3. Custom Traffic / Speed
Run 50 customers with a shorter delay between actions:
```bash
python customer_simulator.py --customers 50 --delay 0.2
```

#### 4. Targeting a Remote or Custom URL
```bash
python customer_simulator.py --base-url http://192.168.1.100:8080
```

---

### ⚙️ Command-Line Options

| Flag | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `--base-url` | `str` | `http://localhost:8080` | Base URL of the Online Boutique frontend |
| `--customers` | `int` | `10` | Number of customer journeys to simulate per iteration |
| `--delay` | `float` | `0.5` | Base delay (seconds) between actions |
| `--min-items` | `int` | `1` | Minimum items added to cart |
| `--max-items` | `int` | `5` | Maximum items added to cart |
| `--metrics-port` | `int` | `9091` | Port exposing Prometheus metrics (`/metrics`) |
| `--loop` | flag | `False` | Run continuously in an infinite loop |
| `--loop-pause` | `float` | `2.0` | Sleep duration (seconds) between loop iterations |

---

### 📊 Prometheus Metrics Reference

Metrics are exported on `http://localhost:9091/metrics`:

| Metric Name | Type | Labels | Description |
| :--- | :--- | :--- | :--- |
| `customer_sim_requests_total` | Counter | `endpoint`, `status` | Total HTTP requests made by endpoint and status code |
| `customer_sim_request_duration_seconds` | Histogram | `endpoint` | HTTP latency distribution per endpoint |
| `customer_sim_journeys_total` | Counter | `outcome` (`success` / `failure`) | Total customer journeys completed |
| `customer_sim_journey_duration_seconds` | Histogram | None | Total end-to-end journey duration |
| `customer_sim_active_customers` | Gauge | None | Number of customer sessions currently running |
| `customer_sim_cart_items_added_total` | Counter | None | Total quantity of items added to cart |
| `customer_sim_checkouts_total` | Counter | `outcome` (`success` / `failure` / `error`) | Total checkout attempts |

#### Prometheus Scrape Configuration
Add this job to your `prometheus.yml`:
```yaml
scrape_configs:
  - job_name: 'customer_simulator'
    static_configs:
      - targets: ['localhost:9091']
```

---

### 🔍 Error Tracking & Diagnostics

When chaos is injected (e.g. killing `cartservice`, adding latency to `productcatalogservice`, or network partitions), the simulator isolates failures:

1. **Immediate Step Logs**: Displays exact failing HTTP method and URL in real time.
2. **Per-Customer Trace**: Summarizes all failing requests for each individual customer session.
3. **Iteration Summary Table**:
   ```
   🔴 ERROR DETAILS (2 total)
   ────────────────────────────────────────────────────────
   #    Method Path                      Status   Customer
   ────────────────────────────────────────────────────────
   1    POST   /cart                     500      e3f942ba
   2    POST   /cart/checkout            503      a82110c9
   ────────────────────────────────────────────────────────

   📝 Error Bodies:
   [1] POST http://localhost:8080/cart
       Body: Could not add item to cart: rpc error: code = Unavailable
   ```

---

## 🛠️ Cluster Setup & Chaos Injection

1. **Start Cluster & Online Boutique:**
   ```bash
   kind create cluster --name chaos
   kubectl apply -f https://raw.githubusercontent.com/GoogleCloudPlatform/microservices-demo/main/release/kubernetes-manifests.yaml
   kubectl port-forward svc/frontend 8080:80
   ```

2. **Start Customer Simulator:**
   ```bash
   python customer_simulator.py --loop
   ```

3. **Inject Faults with Chaos Mesh:**
   - Apply chaos manifests from `./experiments/`
   - Monitor failure detection and automatic kill-switch safeguards
