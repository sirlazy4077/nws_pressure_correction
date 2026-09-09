"""One place where HTTP happens.

Kept tiny and dependency-free (stdlib urllib) so the package needs no requests
install, and so tests can monkeypatch a single function to run offline.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from .config import HTTP_TIMEOUT_S, USER_AGENT


class HttpError(Exception):
    """Any failure reaching or parsing a JSON endpoint."""


def build_url(base: str, params: dict[str, Any]) -> str:
    clean = {k: v for k, v in params.items() if v is not None}
    return f"{base}?{urllib.parse.urlencode(clean)}"


def get_json(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: float = HTTP_TIMEOUT_S,
) -> Any:
    """GET a URL and parse JSON.

    Every network failure - DNS, TLS, timeout, HTTP 4xx/5xx, malformed body -
    surfaces as HttpError, so a caller walking a fallback chain has exactly one
    exception type to catch. The old code caught only IndexError, which is why
    the three most likely real-world failures were the three that killed it.
    """
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        raise HttpError(f"HTTP {exc.code} from {url}") from exc
    except urllib.error.URLError as exc:
        raise HttpError(f"Could not reach {url}: {exc.reason}") from exc
    except OSError as exc:  # socket timeouts, TLS failures
        raise HttpError(f"Could not reach {url}: {exc}") from exc
    try:
        return json.loads(raw.decode("utf-8", errors="replace"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise HttpError(f"Malformed JSON from {url}") from exc
