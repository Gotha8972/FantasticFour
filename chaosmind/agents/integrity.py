"""Integrity checks: catch failures that LOOK healthy (HTTP 200) but aren't. Plain code, no AI.

prepare() before the fault puts an item in a fresh cart; verify(state) after recovery checks the cart still has it
and that a brand-new checkout really produces an order. The Redis restart wiped carts with 0 HTTP errors; this is
what catches it.
"""
import http.cookiejar
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

from chaosmind import app, inject
from chaosmind.c_tests import cart_count

BASE = os.environ.get('FRONTEND_URL', 'http://localhost:8080')
PRODUCT = 'OLJCESPC7Z'
# Same demo values the shop's own checkout form is pre-filled with.
CHECKOUT_FORM = {'email': 'someone@example.com', 'street_address': '1600 Amphitheatre Parkway', 'zip_code': '94043',
                 'city': 'Mountain View', 'state': 'CA', 'country': 'United States',
                 'credit_card_number': '4432801561520454', 'credit_card_expiration_month': '1',
                 'credit_card_expiration_year': '2030', 'credit_card_cvv': '672'}
# Online Boutique's order.html wording; confirmed on the live shop (a healthy checkout verifies with no violations).
ORDER_PLACED = re.compile(r'order confirmation id|your order is complete', re.I)


def new_session():
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))


def fetch(session, path, form=None):
    """(status, html). A timeout or connection error is status None, never an exception."""
    data = urllib.parse.urlencode(form).encode() if form else None
    try:
        with session.open(BASE + path, data, timeout=3) as response:
            return response.status, response.read().decode(errors='replace')
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode(errors='replace')
    except OSError as error:
        return None, str(error)


def items_in_cart(session):
    status, html = fetch(session, '/cart')
    if status != 200:
        return None, f'GET /cart -> {status}'
    try:
        return cart_count(html), html
    except RuntimeError as error:
        return None, str(error)


def boutique_prepare():
    """Before the fault: one item in a fresh cart. Returns the state verify() needs."""
    session = new_session()
    fetch(session, '/')
    fetch(session, '/cart', {'product_id': PRODUCT, 'quantity': 1})
    count, _ = items_in_cart(session)
    return {'session': session, 'cart_before': count}


def boutique_verify(state):
    """After recovery: list of violations ([] = everything correct)."""
    violations = []
    if state.get('cart_before'):
        count, detail = items_in_cart(state['session'])
        if count is None:
            violations.append({'check': 'cart_persistence', 'expected': f"{state['cart_before']} item(s)",
                               'actual': 'cart unreadable', 'evidence': detail[:200]})
        elif count < state['cart_before']:
            violations.append({'check': 'cart_persistence', 'expected': f"{state['cart_before']} item(s)",
                               'actual': f'{count} item(s)', 'evidence': 'same session, cart emptied by the fault'})
    buyer = new_session()
    fetch(buyer, '/')
    fetch(buyer, '/cart', {'product_id': PRODUCT, 'quantity': 1})
    status, html = fetch(buyer, '/cart/checkout', CHECKOUT_FORM)
    if status != 200 or not ORDER_PLACED.search(html):
        violations.append({'check': 'checkout_completes', 'expected': 'HTTP 200 with an order confirmation',
                           'actual': f'HTTP {status}', 'evidence': re.sub(r'\s+', ' ', html)[:200]})
    return violations


if __name__ == '__main__':
    import json
    s = prepare()
    print('state before:', {k: v for k, v in s.items() if k != 'session'})
    print(json.dumps(verify(s), indent=1))


# ── per app ──────────────────────────────────────────────────────────────────
# Integrity checks are the one part that must know what "correct" means for an app. Online Boutique: the cart is kept
# and checkout produces an order. Apps with "integrity": "page" list page checks in their profile: after recovery the
# page must render in full (HTTP 200 alone isn't trusted). Fetched from inside the cluster, from the load generator pod.

PAGE_FETCH = r'''
import json, sys, urllib.error, urllib.request
out = []
for c in json.loads(sys.stdin.readline()):
    try:
        with urllib.request.urlopen(c["url"], timeout=5) as r:
            out.append({"status": r.status, "body": r.read().decode(errors="replace")})
    except urllib.error.HTTPError as e:
        out.append({"status": e.code, "body": e.read().decode(errors="replace")})
    except Exception as e:
        out.append({"status": None, "body": str(e)})
print(json.dumps(out))
'''


def page_verify():
    checks = app.PAGE_CHECKS
    fetched = json.loads(inject.kubectl('exec', '-i', f'deployment/{app.LOADGENERATOR}', '-n', inject.NS, '-c', 'main',
                                        '--', 'python', '-c', PAGE_FETCH, stdin=json.dumps(checks) + '\n'))
    violations = []
    for c, got in zip(checks, fetched):
        missing = [s for s in c.get('must_contain', []) if s not in got['body']]
        present = [s for s in c.get('must_not_contain', []) if s in got['body']]
        if got['status'] != 200 or missing or present:
            violations.append({'check': c['name'], 'expected': c.get('expected', 'HTTP 200 with the full page'),
                               'actual': f"HTTP {got['status']}" + (f'; missing {missing}' if missing else '')
                                         + (f'; shows {present}' if present else ''),
                               'evidence': re.sub(r'\s+', ' ', got['body'])[:200]})
    return violations


def prepare():
    """Before the fault: whatever verify() needs (Online Boutique: one item in a fresh cart)."""
    return boutique_prepare() if app.INTEGRITY == 'online-boutique' else {}


def verify(state):
    """After recovery: list of violations ([] = everything correct)."""
    if app.INTEGRITY == 'online-boutique':
        return boutique_verify(state)
    return page_verify() if app.INTEGRITY == 'page' else []
