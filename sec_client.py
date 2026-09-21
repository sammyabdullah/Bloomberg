"""Thin, rate-limited, caching HTTP client for SEC EDGAR's XBRL APIs."""

import json
import logging
import time
from pathlib import Path
from typing import Optional

import requests

logger = logging.getLogger(__name__)

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik10}.json"

MAX_REQUESTS_PER_SECOND = 10
MIN_INTERVAL = 1.0 / MAX_REQUESTS_PER_SECOND


class RateLimiter:
    """Enforces a minimum interval between successive calls (sequential use)."""

    def __init__(self, min_interval: float = MIN_INTERVAL):
        self.min_interval = min_interval
        self._last_call = 0.0

    def wait(self):
        now = time.monotonic()
        elapsed = now - self._last_call
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self._last_call = time.monotonic()


class SECClient:
    def __init__(
        self,
        user_agent: str,
        cache_dir: Path,
        force_refresh: bool = False,
        max_retries: int = 3,
    ):
        if not user_agent or "@" not in user_agent or user_agent.strip().startswith("Your Name"):
            raise ValueError(
                "A descriptive User-Agent with your real name and email is required by SEC "
                "(e.g. 'Jane Doe jane@example.com'). Set it in config.py, via --user-agent, "
                "or the SEC_EDGAR_USER_AGENT environment variable."
            )
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": user_agent,
                "Accept-Encoding": "gzip, deflate",
            }
        )
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.force_refresh = force_refresh
        self.max_retries = max_retries
        self.rate_limiter = RateLimiter()

    def _get_json(self, url: str) -> Optional[dict]:
        for attempt in range(1, self.max_retries + 1):
            self.rate_limiter.wait()
            try:
                resp = self.session.get(url, timeout=30)
            except requests.RequestException as exc:
                logger.warning(
                    "Request error for %s (attempt %d/%d): %s", url, attempt, self.max_retries, exc
                )
                time.sleep(2 * attempt)
                continue

            if resp.status_code == 404:
                return None
            if resp.status_code == 429 or resp.status_code >= 500:
                logger.warning(
                    "HTTP %s for %s (attempt %d/%d), backing off",
                    resp.status_code,
                    url,
                    attempt,
                    self.max_retries,
                )
                time.sleep(2 * attempt)
                continue
            if resp.status_code != 200:
                logger.warning("Unexpected HTTP %s for %s", resp.status_code, url)
                return None

            try:
                return resp.json()
            except ValueError as exc:
                logger.warning("Malformed JSON from %s: %s", url, exc)
                return None

        logger.warning("Giving up on %s after %d attempts", url, self.max_retries)
        return None

    def get_company_tickers(self) -> dict:
        """Download (or load cached) SEC ticker -> CIK mapping file."""
        cache_path = self.cache_dir / "company_tickers.json"
        if cache_path.exists() and not self.force_refresh:
            try:
                with cache_path.open() as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Cached company_tickers.json unreadable (%s), re-downloading", exc)

        data = self._get_json(TICKERS_URL)
        if data is None:
            if cache_path.exists():
                logger.warning("Download failed; falling back to stale cached company_tickers.json")
                with cache_path.open() as f:
                    return json.load(f)
            raise RuntimeError(
                "Could not download company_tickers.json from SEC and no cache is available."
            )

        with cache_path.open("w") as f:
            json.dump(data, f)
        return data

    def get_company_facts(self, cik10: str) -> Optional[dict]:
        """Download (or load cached) XBRL company facts for a 10-digit zero-padded CIK.

        Returns None if SEC has no XBRL facts for this CIK (e.g. HTTP 404).
        """
        cache_path = self.cache_dir / f"CIK{cik10}.json"
        if cache_path.exists() and not self.force_refresh:
            try:
                with cache_path.open() as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Cached facts for CIK%s unreadable (%s), re-downloading", cik10, exc)

        url = COMPANYFACTS_URL.format(cik10=cik10)
        data = self._get_json(url)
        if data is None:
            return None

        with cache_path.open("w") as f:
            json.dump(data, f)
        return data
