from __future__ import annotations

import asyncio
import logging

import httpx

log = logging.getLogger("chakravyuh.http")

RETRY_STATUS = {408, 429, 500, 502, 503, 504}


class GnaniAPIError(RuntimeError):
    def __init__(self, status: int, body: str, what: str):
        super().__init__(f"{what}: HTTP {status}: {body[:500]}")
        self.status = status
        self.body = body


async def request_with_retry(client: httpx.AsyncClient, method: str, url: str, *, what: str, attempts: int = 4, **kw) -> httpx.Response:
    delay = 1.0
    for i in range(attempts):
        try:
            r = await client.request(method, url, **kw)
        except (httpx.TransportError, httpx.TimeoutException) as e:
            if i == attempts - 1:
                raise GnaniAPIError(0, str(e), what) from e
            log.warning("%s: transport error %s, retrying in %.0fs", what, e, delay)
        else:
            if r.status_code < 400:
                return r
            if r.status_code not in RETRY_STATUS or i == attempts - 1:
                raise GnaniAPIError(r.status_code, r.text, what)
            log.warning("%s: HTTP %s, retrying in %.0fs", what, r.status_code, delay)
        await asyncio.sleep(delay)
        delay *= 2
    raise AssertionError("unreachable")
