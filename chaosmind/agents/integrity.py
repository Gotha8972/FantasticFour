"""Integrity checks: catch failures that LOOK healthy (HTTP 200) but aren't. Plain code, no AI.

prepare() before the fault puts an item in a fresh cart; verify(state) after recovery checks the cart still has it
and that a brand-new checkout really produces an order. The Redis restart wiped carts with 0 HTTP errors; this is
what catches it.
"""
import http.cookiejar
import os
import re
import urllib.error
import urllib.parse
import urllib.request

from chaosmind.c_tests import cart_count

BASE = os.environ.get('FRONTEND_URL', 'http://localhost:8080')
PRODUCT = 'OLJCESPC7Z'
# Same demo values the shop's own checkout form is pre-filled with.
CHECKOUT_FORM = {'email': 'someone@example.com', 'street_address': '1600 Amphitheatre Parkway', 'zip_code': '94043',
                 'city': 'Mountain View', 'state': 'CA', 'country': 'United States',
                 'credit_card_number': '4432801561520454', 'credit_card_expiration_month': '1',
                 'credit_card_expiration_year': '2030', 'credit_card_cvv': '672'}
# ponytail: matched against Online Boutique's order.html wording; confirm once on a live success page.
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


def prepare():
    """Before the fault: one item in a fresh cart. Returns the state verify() needs."""
    session = new_session()
    fetch(session, '/')
    fetch(session, '/cart', {'product_id': PRODUCT, 'quantity': 1})
    count, _ = items_in_cart(session)
    return {'session': session, 'cart_before': count}


def verify(state):
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
    print('cart before:', s['cart_before'])
    print(json.dumps(verify(s), indent=1))
