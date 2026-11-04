from __future__ import annotations

import asyncio
import logging
import random

import httpx

log = logging.getLogger("chakravyuh.http")

RETRY_STATUS = {408, 429, 500, 502, 503, 504}
MAX_RATE_LIMIT_WAITS = 8          # free tiers (Gemini, Groq) rate-limit per minute


class GnaniAPIError(RuntimeError):
    def __init__(self, status: int, body: str, what: str):
        super().__init__(f"{what}: HTTP {status}: {body[:500]}")
        self.status = status
        self.body = body


def _retry_after(r: httpx.Response) -> float | None:
    v = r.headers.get("retry-after")
    try:
        return min(90.0, float(v)) if v else None
    except ValueError:
        return None


async def request_with_retry(client: httpx.AsyncClient, method: str, url: str, *, what: str, attempts: int = 4, **kw) -> httpx.Response:
    delay = 1.0
    errors = rate_limited = 0
    while True:
        try:
            r = await client.request(method, url, **kw)
        except (httpx.TransportError, httpx.TimeoutException) as e:
            errors += 1
            if errors >= attempts:
                raise GnaniAPIError(0, f"{type(e).__name__}: {e}", what) from e
            log.warning("%s: transport error %s, retrying in %.0fs", what, e, delay)
            wait = delay
        else:
            if r.status_code < 400:
                return r
            if r.status_code == 429 and rate_limited < MAX_RATE_LIMIT_WAITS:
                rate_limited += 1
                wait = _retry_after(r) or min(60.0, 5.0 * 2 ** (rate_limited - 1))
                log.warning("%s: rate limited, waiting %.0fs (%d/%d)", what, wait, rate_limited, MAX_RATE_LIMIT_WAITS)
            elif r.status_code in RETRY_STATUS and r.status_code != 429 and errors + 1 < attempts:
                errors += 1
                wait = delay
                log.warning("%s: HTTP %s, retrying in %.0fs", what, r.status_code, wait)
            else:
                raise GnaniAPIError(r.status_code, r.text, what)
        await asyncio.sleep(wait + random.uniform(0, 0.5))
        delay *= 2
