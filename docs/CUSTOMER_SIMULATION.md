# Customer Simulator (`customer_simulator.py`)

A Python simulation tool for testing the resilience and performance of the **Google Online Boutique** microservices application under normal operations and during Chaos Mesh fault injections.

---

## 📋 Overview

The customer simulator automates multi-step, realistic shopping sessions. It performs browsing, currency conversion, cart additions, and checkout transactions while exporting Prometheus metrics and tracking detailed error paths, HTTP status codes, and server response bodies.

---

## 🚀 Key Features

- **Realistic E-Commerce Journey**: Simulates complete end-to-end user actions with natural delays between steps.
- **Prometheus Metrics Exporter**: Exposes live application metrics on port `9091` (`/metrics`).
- **Comprehensive Error Diagnostics**:
  - Detailed failure paths (e.g. `/cart`, `/cart/checkout`).
  - HTTP status codes (4xx, 5xx, or `NET_ERR`).
  - Error snippets and exception traces.
  - Per-customer error summary and aggregated iteration table.
- **Configurable Runtime**: Run a fixed batch of customers or loop continuously during chaos experiments.

---

## 🚶 Customer Journey Workflow

Each customer journey performs the following actions:

1. **Browse Home Page** (`GET /`): Validates frontend availability.
2. **Switch Currency** (`POST /setCurrency`): Randomly selects between `USD`, `EUR`, `JPY`, `CAD`, `GBP`, `TRY`.
3. **View Products** (`GET /product/{id}`): Inspects 1 to 3 random items from the catalog.
4. **Add Items to Cart** (`POST /cart`): Adds 1 to 5 random products with variable quantities.
5. **View Cart** (`GET /cart`): Confirms cart state and item accumulation.
6. **Checkout** (`POST /cart/checkout`): Submits synthetic order details with shipping address and credit card information.

---

## ⏱️ Execution Time & Duration

- **Default Execution (~30–60 seconds)**:
  - Runs **1 iteration** with **10 customers** sequentially.
  - Each customer journey takes roughly **2 to 5 seconds** depending on network latency and randomized delays.
  - After all 10 customers complete, it prints an error and metrics summary and exits.
- **Continuous Mode (`--loop`) (Runs Indefinitely)**:
  - Continuously simulates customer batches until manually stopped with `Ctrl + C`.
  - Pauses between iterations according to `--loop-pause` (default: 2.0s).

---

## 📦 Prerequisites & Installation

### Requirements
- Python 3.10+
- `requests`
- `prometheus_client`

### Setup
```bash
# Activate virtual environment
# Windows:
.\venv\Scripts\Activate.ps1

# Linux / macOS:
source venv/bin/activate

# Install dependencies
pip install requests prometheus_client
```

---

## 💻 Usage Examples

### 1. Standard Run (10 Customers)
```bash
python customer_simulator.py
```

### 2. Continuous Run (Chaos Testing)
Runs continuously to provide constant background load while testing Chaos Mesh injections:
```bash
python customer_simulator.py --loop
```

### 3. Custom Customer Count & Delay
```bash
# 50 customers with faster delays (0.2s)
python customer_simulator.py --customers 50 --delay 0.2
```

### 4. Custom Frontend Target
```bash
python customer_simulator.py --base-url http://localhost:8080
```

---

## ⚙️ Command-Line Arguments

| Argument | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `--base-url` | `str` | `http://localhost:8080` | URL of Online Boutique frontend |
| `--customers` | `int` | `10` | Number of customer journeys to simulate per iteration |
| `--delay` | `float` | `0.5` | Base delay in seconds between actions |
| `--min-items` | `int` | `1` | Minimum number of items added per cart |
| `--max-items` | `int` | `5` | Maximum number of items added per cart |
| `--metrics-port` | `int` | `9091` | Port hosting the Prometheus `/metrics` endpoint |
| `--loop` | flag | `False` | Run continuously in an infinite loop |
| `--loop-pause` | `float` | `2.0` | Pause duration (seconds) between loop cycles |

---

## 📊 Prometheus Metrics

The simulator exposes metrics on `http://localhost:9091/metrics`:

| Metric | Type | Labels | Description |
| :--- | :--- | :--- | :--- |
| `customer_sim_requests_total` | Counter | `endpoint`, `status` | Total HTTP requests sent |
| `customer_sim_request_duration_seconds` | Histogram | `endpoint` | Request latency per endpoint |
| `customer_sim_journeys_total` | Counter | `outcome` (`success`, `failure`) | Total completed customer journeys |
| `customer_sim_journey_duration_seconds` | Histogram | None | Total duration of each customer journey |
| `customer_sim_active_customers` | Gauge | None | Number of customer sessions currently running |
| `customer_sim_cart_items_added_total` | Counter | None | Total quantity of items added to carts |
| `customer_sim_checkouts_total` | Counter | `outcome` (`success`, `failure`, `error`) | Total checkout attempts |

---

## 🔴 Error Output & Diagnostics

When an HTTP or network error occurs, the script captures:
- **HTTP Method & Path**: e.g., `POST /cart`, `POST /cart/checkout`
- **Status Code**: e.g., `500 Internal Server Error`, `503 Service Unavailable`, or `NET_ERR`
- **Error Body Snippet**: Server error responses or gRPC error messages
- **Customer ID**: Associated customer trace identifier

### Sample Terminal Output
```text
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
