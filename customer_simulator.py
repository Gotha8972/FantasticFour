#!/usr/bin/env python3
"""
Online Boutique — Customer Simulator
=====================================
Simulates realistic customer journeys against the Online Boutique frontend:
  1. Browse the home page
  2. Set a random currency
  3. Browse random products
  4. Add items to cart
  5. View the cart
  6. Checkout with fake user details

Each "customer" is a fresh requests.Session (new session cookie).
Metrics are exported via prometheus_client on :9091/metrics so Prometheus
can scrape them alongside the app.

Error reporting:
  - Every failed request logs the full URL path, HTTP status code, and
    a truncated snippet of the response body.
  - The per-iteration summary prints a structured error table.

Usage:
    python customer_simulator.py                     # 10 customers, default settings
    python customer_simulator.py --customers 50      # 50 customers
    python customer_simulator.py --base-url http://10.0.0.5:8080 --delay 0.5
    python customer_simulator.py --metrics-port 9091  # change Prometheus port
"""

import argparse
import random
import re
import sys
import time
import traceback
import uuid
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urlparse

import requests
from prometheus_client import (
    Counter,
    Histogram,
    Gauge,
    start_http_server,
)

# ──────────────────────────────────────────────
# Prometheus metrics
# ──────────────────────────────────────────────
REQUEST_COUNT = Counter(
    "customer_sim_requests_total",
    "Total HTTP requests made by the simulator",
    ["method", "endpoint", "status"],
)
REQUEST_LATENCY = Histogram(
    "customer_sim_request_duration_seconds",
    "Latency of each HTTP request",
    ["method", "endpoint"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)
JOURNEY_COUNT = Counter(
    "customer_sim_journeys_total",
    "Total customer journeys attempted",
    ["outcome"],  # "success" or "failure"
)
JOURNEY_LATENCY = Histogram(
    "customer_sim_journey_duration_seconds",
    "End-to-end latency per customer journey",
)
ACTIVE_CUSTOMERS = Gauge(
    "customer_sim_active_customers",
    "Number of customer sessions currently running",
)
CART_ITEMS_ADDED = Counter(
    "customer_sim_cart_items_added_total",
    "Total items added to carts",
)
CHECKOUTS = Counter(
    "customer_sim_checkouts_total",
    "Total checkout attempts",
    ["outcome"],
)

# ──────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────
PRODUCTS = [
    "0PUK6V6EV0",
    "1YMWWN1N4O",
    "2ZYFJ3GM2N",
    "66VCHSJNUP",
    "6E92ZMYYFZ",
    "9SIQT8TOJO",
    "L9ECAV7KIM",
    "LS4PSXUNUM",
    "OLJCESPC7Z",
]

CURRENCIES = ["USD", "EUR", "JPY", "CAD", "GBP", "TRY"]

# Fake addresses for checkout
FAKE_ADDRESSES = [
    {
        "street_address": "1600 Amphitheatre Parkway",
        "city": "Mountain View",
        "state": "CA",
        "zip_code": "94043",
        "country": "United States",
    },
    {
        "street_address": "1 Hacker Way",
        "city": "Menlo Park",
        "state": "CA",
        "zip_code": "94025",
        "country": "United States",
    },
    {
        "street_address": "410 Terry Ave N",
        "city": "Seattle",
        "state": "WA",
        "zip_code": "98109",
        "country": "United States",
    },
    {
        "street_address": "221B Baker Street",
        "city": "London",
        "state": "",
        "zip_code": "NW1 6XE",
        "country": "United Kingdom",
    },
    {
        "street_address": "Friedrichstraße 43-45",
        "city": "Berlin",
        "state": "",
        "zip_code": "10117",
        "country": "Germany",
    },
]

FAKE_CREDIT_CARDS = [
    {"number": "4432-8015-6152-0454", "expiry_month": "1", "expiry_year": "2030", "cvv": "672"},
    {"number": "4916-1234-5678-9012", "expiry_month": "6", "expiry_year": "2029", "cvv": "123"},
    {"number": "5425-2334-3010-9903", "expiry_month": "12", "expiry_year": "2028", "cvv": "456"},
]

FAKE_EMAILS = [
    "shopper@example.com",
    "test.buyer@demo.org",
    "chaos.customer@boutique.dev",
    "resilience.tester@k8s.local",
    "alice@wonderland.io",
]

# ──────────────────────────────────────────────
# Formatting helpers
# ──────────────────────────────────────────────
CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
MAGENTA = "\033[95m"
DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"


def _ts() -> str:
    return time.strftime("%H:%M:%S")


def _truncate(text: str, max_len: int = 200) -> str:
    """Truncate text and strip HTML tags for readable error snippets."""
    clean = re.sub(r"<[^>]+>", " ", text)
    clean = re.sub(r"\s+", " ", clean).strip()
    if len(clean) > max_len:
        return clean[:max_len] + "…"
    return clean


def log_step(customer_id: str, icon: str, msg: str):
    print(f"  {CYAN}[{_ts()}]{RESET} {icon}  {BOLD}Customer {customer_id[:8]}{RESET} │ {msg}")


def log_ok(customer_id: str, msg: str):
    log_step(customer_id, f"{GREEN}✔{RESET}", f"{GREEN}{msg}{RESET}")


def log_warn(customer_id: str, msg: str):
    log_step(customer_id, f"{YELLOW}⚠{RESET}", f"{YELLOW}{msg}{RESET}")


def log_fail(customer_id: str, msg: str):
    log_step(customer_id, f"{RED}✖{RESET}", f"{RED}{msg}{RESET}")


def log_header(msg: str):
    print(f"\n{'─' * 60}")
    print(f"  {MAGENTA}{BOLD}{msg}{RESET}")
    print(f"{'─' * 60}")


# ──────────────────────────────────────────────
# Error detail container
# ──────────────────────────────────────────────
@dataclass
class RequestError:
    """Structured error for a single failed HTTP request."""
    method: str
    path: str
    full_url: str
    status_code: Optional[int]  # None for network errors
    body_snippet: str
    error_type: str  # "http" or "network"
    exception: Optional[str] = None

    def short(self) -> str:
        if self.error_type == "network":
            return f"{self.method} {self.path} → NETWORK ERROR: {self.exception}"
        return f"{self.method} {self.path} → {self.status_code}"

    def detail(self) -> str:
        lines = [
            f"{RED}✖ {self.method} {self.full_url}{RESET}",
        ]
        if self.status_code is not None:
            lines.append(f"  Status : {self.status_code}")
        if self.exception:
            lines.append(f"  Error  : {self.exception}")
        if self.body_snippet:
            lines.append(f"  Body   : {DIM}{self.body_snippet}{RESET}")
        return "\n".join(lines)


# ──────────────────────────────────────────────
# HTTP helpers with metric recording
# ──────────────────────────────────────────────
def _get(
    session: requests.Session,
    url: str,
    endpoint_label: str,
    errors: list,
    **kwargs,
) -> Optional[requests.Response]:
    """GET with metrics and error capture."""
    path = urlparse(url).path
    try:
        with REQUEST_LATENCY.labels(method="GET", endpoint=endpoint_label).time():
            resp = session.get(url, timeout=15, **kwargs)
        REQUEST_COUNT.labels(method="GET", endpoint=endpoint_label, status=str(resp.status_code)).inc()
        if resp.status_code >= 400:
            err = RequestError(
                method="GET", path=path, full_url=url,
                status_code=resp.status_code,
                body_snippet=_truncate(resp.text),
                error_type="http",
            )
            errors.append(err)
            log_fail("", f"{err.short()}")
            log_step("", " ", f"{DIM}Body: {err.body_snippet}{RESET}")
        return resp
    except requests.RequestException as exc:
        REQUEST_COUNT.labels(method="GET", endpoint=endpoint_label, status="error").inc()
        err = RequestError(
            method="GET", path=path, full_url=url,
            status_code=None, body_snippet="",
            error_type="network", exception=str(exc),
        )
        errors.append(err)
        raise exc


def _post(
    session: requests.Session,
    url: str,
    endpoint_label: str,
    data: dict,
    errors: list,
    **kwargs,
) -> Optional[requests.Response]:
    """POST with metrics and error capture."""
    path = urlparse(url).path
    try:
        with REQUEST_LATENCY.labels(method="POST", endpoint=endpoint_label).time():
            resp = session.post(url, data=data, timeout=15, **kwargs)
        REQUEST_COUNT.labels(method="POST", endpoint=endpoint_label, status=str(resp.status_code)).inc()
        if resp.status_code >= 400:
            err = RequestError(
                method="POST", path=path, full_url=url,
                status_code=resp.status_code,
                body_snippet=_truncate(resp.text),
                error_type="http",
            )
            errors.append(err)
            log_fail("", f"{err.short()}")
            log_step("", " ", f"{DIM}Body: {err.body_snippet}{RESET}")
        return resp
    except requests.RequestException as exc:
        REQUEST_COUNT.labels(method="POST", endpoint=endpoint_label, status="error").inc()
        err = RequestError(
            method="POST", path=path, full_url=url,
            status_code=None, body_snippet="",
            error_type="network", exception=str(exc),
        )
        errors.append(err)
        raise exc


# ──────────────────────────────────────────────
# Customer journey
# ──────────────────────────────────────────────
@dataclass
class JourneyResult:
    customer_id: str
    success: bool
    items_added: int = 0
    checkout_ok: bool = False
    errors: list = field(default_factory=list)       # list[RequestError]
    error_labels: list = field(default_factory=list)  # legacy short labels
    duration_s: float = 0.0


def run_customer_journey(
    base_url: str,
    delay: float = 0.3,
    min_items: int = 1,
    max_items: int = 5,
) -> JourneyResult:
    """
    Simulate a single customer journey:
      1. Browse home page
      2. Set a random currency
      3. Browse 1-3 random product pages
      4. Add 1-5 random items to the cart
      5. View the cart
      6. Checkout
    """
    customer_id = uuid.uuid4().hex
    session = requests.Session()
    result = JourneyResult(customer_id=customer_id, success=False)
    req_errors: list[RequestError] = []   # collect errors from helpers
    t0 = time.time()

    ACTIVE_CUSTOMERS.inc()
    try:
        # ── Step 1: Home page ──
        log_step(customer_id, "🏠", "Browsing home page …")
        resp = _get(session, f"{base_url}/", "/", req_errors)
        if resp.status_code != 200:
            log_fail(customer_id, f"Home page returned {resp.status_code}")
            return result
        log_ok(customer_id, f"Home page loaded ({resp.status_code})")
        time.sleep(random.uniform(delay * 0.5, delay * 1.5))

        # ── Step 2: Set currency ──
        currency = random.choice(CURRENCIES)
        log_step(customer_id, "💱", f"Setting currency to {currency}")
        resp = _post(session, f"{base_url}/setCurrency", "/setCurrency", {"currency_code": currency}, req_errors)
        if resp.status_code != 200:
            log_warn(customer_id, f"setCurrency returned {resp.status_code} (non-fatal)")
        else:
            log_ok(customer_id, f"Currency set to {currency}")
        time.sleep(random.uniform(delay * 0.3, delay))

        # ── Step 3: Browse products ──
        num_browse = random.randint(1, 3)
        browsed_products = random.sample(PRODUCTS, min(num_browse, len(PRODUCTS)))
        for pid in browsed_products:
            log_step(customer_id, "🔍", f"Viewing product {pid}")
            resp = _get(session, f"{base_url}/product/{pid}", "/product", req_errors)
            if resp.status_code == 200:
                log_ok(customer_id, f"Product {pid} loaded")
            else:
                log_warn(customer_id, f"Product {pid} returned {resp.status_code}")
            time.sleep(random.uniform(delay * 0.3, delay))

        # ── Step 4: Add items to cart ──
        num_items = random.randint(min_items, max_items)
        items_to_add = random.choices(PRODUCTS, k=num_items)
        for pid in items_to_add:
            quantity = random.randint(1, 3)
            log_step(customer_id, "🛒", f"Adding {quantity}x {pid} to cart")
            resp = _post(
                session,
                f"{base_url}/cart",
                "/cart (add)",
                {"product_id": pid, "quantity": str(quantity)},
                req_errors,
            )
            if resp.status_code == 200:
                log_ok(customer_id, f"Added {quantity}x {pid} ✓")
                result.items_added += quantity
                CART_ITEMS_ADDED.inc(quantity)
            else:
                log_fail(customer_id, f"Add-to-cart failed ({resp.status_code})")
            time.sleep(random.uniform(delay * 0.2, delay * 0.8))

        # ── Step 5: View cart ──
        log_step(customer_id, "📋", "Viewing cart …")
        resp = _get(session, f"{base_url}/cart", "/cart (view)", req_errors)
        if resp.status_code == 200:
            log_ok(customer_id, f"Cart loaded ({result.items_added} items added)")
        else:
            log_warn(customer_id, f"Cart view returned {resp.status_code}")
        time.sleep(random.uniform(delay * 0.5, delay * 1.5))

        # ── Step 6: Checkout ──
        address = random.choice(FAKE_ADDRESSES)
        card = random.choice(FAKE_CREDIT_CARDS)
        email = random.choice(FAKE_EMAILS)

        checkout_data = {
            "email": email,
            "street_address": address["street_address"],
            "zip_code": address["zip_code"],
            "city": address["city"],
            "state": address["state"],
            "country": address["country"],
            "credit_card_number": card["number"],
            "credit_card_expiration_month": card["expiry_month"],
            "credit_card_expiration_year": card["expiry_year"],
            "credit_card_cvv": card["cvv"],
        }

        log_step(customer_id, "💳", f"Checking out → {email}")
        resp = _post(session, f"{base_url}/cart/checkout", "/cart/checkout", checkout_data, req_errors)
        if resp.status_code == 200:
            log_ok(customer_id, f"🎉 Checkout SUCCESS — order placed!")
            result.checkout_ok = True
            result.success = True
            CHECKOUTS.labels(outcome="success").inc()
        else:
            log_fail(customer_id, f"Checkout FAILED ({resp.status_code})")
            CHECKOUTS.labels(outcome="failure").inc()

    except requests.RequestException as exc:
        log_fail(customer_id, f"Network error: {exc}")
        CHECKOUTS.labels(outcome="error").inc()
    finally:
        result.duration_s = time.time() - t0
        result.errors = req_errors
        ACTIVE_CUSTOMERS.dec()

        # ── Per-customer error summary ──
        if req_errors:
            print(f"\n  {RED}{'─' * 50}{RESET}")
            print(f"  {RED}{BOLD}Errors for customer {customer_id[:8]}:{RESET}")
            for i, err in enumerate(req_errors, 1):
                print(f"  {RED}{i}. {err.method} {err.path}{RESET}")
                print(f"     URL    : {DIM}{err.full_url}{RESET}")
                if err.status_code is not None:
                    print(f"     Status : {err.status_code}")
                if err.exception:
                    print(f"     Error  : {err.exception}")
                if err.body_snippet:
                    print(f"     Body   : {DIM}{err.body_snippet}{RESET}")
            print(f"  {RED}{'─' * 50}{RESET}")

    return result


# ──────────────────────────────────────────────
# Main loop
# ──────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Simulate customer journeys on Online Boutique",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--base-url",
        default="http://localhost:8080",
        help="Frontend base URL (default: http://localhost:8080)",
    )
    parser.add_argument(
        "--customers",
        type=int,
        default=10,
        help="Number of customer journeys to simulate (default: 10)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.5,
        help="Base delay between actions in seconds (default: 0.5)",
    )
    parser.add_argument(
        "--min-items",
        type=int,
        default=1,
        help="Minimum items per cart (default: 1)",
    )
    parser.add_argument(
        "--max-items",
        type=int,
        default=5,
        help="Maximum items per cart (default: 5)",
    )
    parser.add_argument(
        "--metrics-port",
        type=int,
        default=9091,
        help="Port for Prometheus metrics endpoint (default: 9091)",
    )
    parser.add_argument(
        "--loop",
        action="store_true",
        help="Run forever in a continuous loop",
    )
    parser.add_argument(
        "--loop-pause",
        type=float,
        default=2.0,
        help="Pause between loop iterations in seconds (default: 2.0)",
    )
    args = parser.parse_args()

    # Start Prometheus metrics server
    print(f"\n{BOLD}📊 Prometheus metrics → http://localhost:{args.metrics_port}/metrics{RESET}")
    start_http_server(args.metrics_port)

    iteration = 0
    while True:
        iteration += 1
        log_header(f"▶ Iteration {iteration} — {args.customers} customer(s) → {args.base_url}")

        results: list[JourneyResult] = []
        for i in range(args.customers):
            print(f"\n  {'━' * 50}")
            print(f"  {BOLD}Customer {i + 1}/{args.customers}{RESET}")
            print(f"  {'━' * 50}")

            result = run_customer_journey(
                base_url=args.base_url,
                delay=args.delay,
                min_items=args.min_items,
                max_items=args.max_items,
            )
            results.append(result)

            JOURNEY_LATENCY.observe(result.duration_s)
            JOURNEY_COUNT.labels(outcome="success" if result.success else "failure").inc()

            # Small pause between customers
            if i < args.customers - 1:
                time.sleep(random.uniform(args.delay, args.delay * 2))

        # ── Summary ──
        successes = sum(1 for r in results if r.success)
        failures = len(results) - successes
        total_items = sum(r.items_added for r in results)
        avg_duration = sum(r.duration_s for r in results) / len(results) if results else 0

        print(f"\n{'═' * 60}")
        print(f"  {BOLD}📊 ITERATION {iteration} SUMMARY{RESET}")
        print(f"{'═' * 60}")
        print(f"  {GREEN}✔ Successful checkouts:{RESET}  {successes}/{len(results)}")
        print(f"  {RED}✖ Failed checkouts:{RESET}      {failures}/{len(results)}")
        print(f"  🛒 Total items added:       {total_items}")
        print(f"  ⏱  Avg journey time:        {avg_duration:.2f}s")

        # Collect all errors across all customers
        all_errors: list[tuple[str, RequestError]] = []
        for r in results:
            for err in r.errors:
                all_errors.append((r.customer_id, err))

        if all_errors:
            print(f"\n  {RED}{BOLD}🔴 ERROR DETAILS ({len(all_errors)} total){RESET}")
            print(f"  {'─' * 56}")
            print(f"  {BOLD}{'#':<4} {'Method':<6} {'Path':<25} {'Status':<8} {'Customer'}{RESET}")
            print(f"  {'─' * 56}")
            for i, (cid, err) in enumerate(all_errors, 1):
                status_str = str(err.status_code) if err.status_code else "NET_ERR"
                print(f"  {i:<4} {err.method:<6} {err.path:<25} {status_str:<8} {cid[:8]}")
            print(f"  {'─' * 56}")

            # Detailed body snippets for each error
            print(f"\n  {YELLOW}{BOLD}📝 Error Bodies:{RESET}")
            for i, (cid, err) in enumerate(all_errors, 1):
                print(f"  {YELLOW}[{i}] {err.method} {err.full_url}{RESET}")
                if err.exception:
                    print(f"      Exception: {err.exception}")
                if err.body_snippet:
                    print(f"      Body: {DIM}{err.body_snippet}{RESET}")
                print()

        print(f"{'═' * 60}\n")

        if not args.loop:
            break

        print(f"  💤 Pausing {args.loop_pause}s before next iteration …")
        time.sleep(args.loop_pause)

    # Final exit summary
    print(f"{BOLD}Done. Ran {iteration} iteration(s).{RESET}")
    return 0 if all(r.success for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
