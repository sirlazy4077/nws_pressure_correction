"""One place where HTTP happens.

Kept tiny and dependency-free (stdlib urllib) so the package needs no requests
install, and so tests can monkeypatch a single function to run offline.

**On TLS trust.** A clinic network commonly intercepts HTTPS: a proxy
terminates the connection and re-signs it with a private CA. Managed
workstations trust that CA - it is pushed in by group policy - which is why a
browser reaches these APIs happily while Python does not. Python verifies
against its own bundled CA list, which has never heard of the proxy.

`truststore` fixes that by verifying through the operating system's own trust
store, the same one the browser uses. It is used automatically when installed
and is a harmless no-op on a normal network, where the OS store and the bundled
list agree.
"""

from __future__ import annotations

import json
import os
import ssl
import urllib.error
import urllib.parse
import urllib.request
from functools import lru_cache
from typing import Any

from .config import HTTP_TIMEOUT_S, user_agent

TRUST_ENV = "BAROME_SYSTEM_TRUST"
_FALSEY = {"0", "false", "no", "off"}


class HttpError(Exception):
    """Any failure reaching or parsing a JSON endpoint."""


@lru_cache(maxsize=1)
def ssl_context() -> ssl.SSLContext | None:
    """An SSL context that verifies against the OS trust store, or None.

    None means "use Python's default", which is the right answer when
    truststore is not installed or has been switched off. Scoped to this
    package's own requests rather than injected globally: a library should not
    silently change TLS behaviour for everything else in the process.
    """
    if os.environ.get(TRUST_ENV, "1").strip().lower() in _FALSEY:
        return None
    try:
        import truststore
    except ImportError:
        return None
    try:
        return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    except Exception:  # pragma: no cover - platform-dependent
        return None


def using_system_trust() -> bool:
    """For the CLI/web diagnostics: is the OS trust store in play?"""
    return ssl_context() is not None


def build_url(base: str, params: dict[str, Any]) -> str:
    clean = {k: v for k, v in params.items() if v is not None}
    return f"{base}?{urllib.parse.urlencode(clean)}"


def certificate_advice() -> str:
    """What to tell a user whose TLS handshake was rejected."""
    if using_system_trust():
        return (
            "TLS certificate rejected even against the system trust store. Ask IT "
            "whether this host is allowed through the proxy."
        )
    return (
        "TLS certificate rejected - this network intercepts HTTPS and Python does "
        "not trust the proxy's certificate. Fix it with: pip install truststore "
        "(then Python verifies against the same store your browser uses). "
        "Alternatively point SSL_CERT_FILE at your proxy's CA bundle."
    )


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
    # user_agent() raises ContactRequiredError, which is deliberately not an
    # HttpError: no fallback chain should swallow it and try the next source.
    request = urllib.request.Request(url, headers={"User-Agent": user_agent(), **(headers or {})})
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=ssl_context()) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        raise HttpError(f"HTTP {exc.code} from {url}") from exc
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, ssl.SSLError):
            raise HttpError(certificate_advice()) from exc
        raise HttpError(f"Could not reach {url}: {exc.reason}") from exc
    except ssl.SSLError as exc:
        raise HttpError(certificate_advice()) from exc
    except OSError as exc:  # socket timeouts and the like
        raise HttpError(f"Could not reach {url}: {exc}") from exc
    try:
        return json.loads(raw.decode("utf-8", errors="replace"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise HttpError(f"Malformed JSON from {url}") from exc
