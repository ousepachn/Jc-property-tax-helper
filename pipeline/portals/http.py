"""A small, polite HTTP session: one request at a time, a minimum gap between
requests, and retries with exponential backoff on network errors / 5xx / 429."""
import time

import requests

USER_AGENT = "jc-property-tax-helper/0.1 (public-records research; github.com/ousepachn/Jc-property-tax-helper)"


class PoliteSession:
    def __init__(self, min_interval=1.0, retries=4, timeout=60):
        self.min_interval = min_interval
        self.retries = retries
        self.timeout = timeout
        self._last = 0.0
        self.s = requests.Session()
        self.s.headers["User-Agent"] = USER_AGENT
        self.requests_made = 0

    def _wait(self):
        gap = time.monotonic() - self._last
        if gap < self.min_interval:
            time.sleep(self.min_interval - gap)

    def request(self, method, url, **kw):
        kw.setdefault("timeout", self.timeout)
        for attempt in range(self.retries + 1):
            self._wait()
            self._last = time.monotonic()
            self.requests_made += 1
            try:
                r = self.s.request(method, url, **kw)
                if r.status_code == 429 or r.status_code >= 500:
                    raise requests.HTTPError(f"HTTP {r.status_code}", response=r)
                r.raise_for_status()
                return r
            except requests.RequestException:
                if attempt == self.retries:
                    raise
                time.sleep(2 ** (attempt + 1))

    def get(self, url, **kw):
        return self.request("GET", url, **kw)

    def post(self, url, **kw):
        return self.request("POST", url, **kw)
