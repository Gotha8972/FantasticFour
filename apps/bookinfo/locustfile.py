"""Bookinfo readers for ChaosMind: the same Locust CSV the guard reads for Online Boutique.

A book page that answers HTTP 200 but is missing its details or reviews counts as a failed request: that is what a
reader sees, and Bookinfo hides those failures behind HTTP 200 by design.
"""
from locust import HttpUser, between, task

DEGRADED = ('currently unavailable',)


class Reader(HttpUser):
    wait_time = between(1, 4)

    @task(5)
    def book_page(self):
        with self.client.get('/productpage?u=normal', name='/productpage', catch_response=True) as r:
            if r.status_code != 200:
                r.failure(f'HTTP {r.status_code}')
            elif any(text in r.text for text in DEGRADED):
                r.failure('page rendered without its details or reviews')
            else:
                r.success()

    @task(1)
    def product_api(self):
        self.client.get('/api/v1/products', name='/api/v1/products')
