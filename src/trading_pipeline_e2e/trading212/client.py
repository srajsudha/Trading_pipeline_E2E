"""Thin, rate-limit-aware client for the Trading 212 public API (v0)."""
import base64
import logging
import time
from typing import Any, Iterator

import requests

log = logging.getLogger(__name__)

HOSTS = {
    "live": "https://live.trading212.com",
    "demo": "https://demo.trading212.com",
}
API_PREFIX = "/api/v0"


class Trading212Client:
    def __init__(self, api_key: str, api_secret: str, env: str = "live",
                 timeout: int = 30, max_retries: int = 5):
        token = base64.b64encode(f"{api_key}:{api_secret}".encode()).decode()
        self.host = HOSTS[env]
        self.timeout = timeout
        self.max_retries = max_retries
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Basic {token}", "Accept": "application/json"})

    def _url(self, path: str) -> str:
        # nextPagePath already contains /api/v0; normal paths do not
        return f"{self.host}{path}" if path.startswith("/api/") else f"{self.host}{API_PREFIX}{path}"

    def get(self, path: str, params: dict | None = None) -> Any:
        url = self._url(path)
        for attempt in range(1, self.max_retries + 1):
            resp = self.session.get(url, params=params, timeout=self.timeout)
            if resp.status_code == 429 or resp.status_code >= 500:
                wait = self._backoff(resp, attempt)
                log.warning("HTTP %s on %s, retry %s/%s in %.0fs", resp.status_code, path, attempt, self.max_retries, wait)
                time.sleep(wait)
                continue
            resp.raise_for_status()  # 401/403/404 fail fast
            return resp.json()
        raise RuntimeError(f"Gave up on {path} after {self.max_retries} attempts")

    @staticmethod
    def _backoff(resp: requests.Response, attempt: int) -> float:
        reset = resp.headers.get("x-ratelimit-reset")      # unix epoch seconds, if provided
        if reset and reset.isdigit():
            return max(float(reset) - time.time(), 1.0) + 1
        retry_after = resp.headers.get("Retry-After")
        if retry_after and retry_after.isdigit():
            return float(retry_after)
        return min(2 ** attempt, 60)

    def paginate(self, path: str, limit: int = 50, min_interval_s: float = 10.5) -> Iterator[dict]:
        """Yield each raw page of a cursor-paginated endpoint.

        History endpoints allow 6 requests per minute, so wait about 10s between pages.
        """
        next_path: str | None = path
        params: dict | None = {"limit": limit}
        while next_path:
            page = self.get(next_path, params=params)
            yield page
            next_path = page.get("nextPagePath")
            params = None  # nextPagePath already carries cursor and limit
            if next_path:
                time.sleep(min_interval_s)