"""Small deterministic source-registry facade for retrieval metadata."""

from __future__ import annotations

from urllib.parse import urlsplit

from .retrieval import ALLOWED_SOURCE_CLASSES


def source_family_id_for_url(url: str) -> str:
    """Return a deterministic source-family ID from a URL hostname."""

    host = urlsplit(url).netloc.lower().removeprefix("www.")
    if not host:
        raise ValueError("url must include a hostname")
    return "source-family:" + host.replace(":", "_")


__all__ = ["ALLOWED_SOURCE_CLASSES", "source_family_id_for_url"]
