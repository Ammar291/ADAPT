"""Browser-origin checks shared by HTTP mutations and WebSocket handshakes."""

from urllib.parse import urlsplit

from app.core.config import Settings


def trusted_origin(origin: str, *, scheme: str, host: str, settings: Settings) -> bool:
    try:
        parsed = urlsplit(origin)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            return False
        normalized = origin.rstrip("/")
        allowed = {o.rstrip("/") for o in settings.cors_origins}
        allowed.add(settings.public_base_url.rstrip("/"))
        http_scheme = {"ws": "http", "wss": "https"}.get(scheme, scheme)
        return normalized in allowed or normalized == f"{http_scheme}://{host}"
    except ValueError:
        return False
