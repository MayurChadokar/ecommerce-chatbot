"""Shared, non-secret configuration and URL handling for product indexing."""

import os
from dataclasses import dataclass
from urllib.parse import quote, urlsplit

EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
EMBEDDING_DIMENSION = 384


@dataclass(frozen=True)
class IndexSettings:
    api_key: str
    name: str
    host: str
    namespace: str

    @classmethod
    def from_env(cls):
        values = {name: os.getenv(name, "").strip() for name in (
            "PINECONE_API_KEY", "PINECONE_INDEX_NAME", "PINECONE_HOST",
            "PINECONE_NAMESPACE",
        )}
        missing = [name for name, value in values.items() if not value]
        if missing:
            raise ValueError("Missing configuration: " + ", ".join(missing))
        host = values["PINECONE_HOST"]
        parsed = urlsplit(host if "://" in host else "https://" + host)
        if (parsed.scheme != "https" or not parsed.hostname
                or not parsed.hostname.endswith(".pinecone.io")
                or parsed.username or parsed.password or parsed.port
                or parsed.path not in ("", "/") or parsed.query or parsed.fragment):
            raise ValueError("PINECONE_HOST must be a Pinecone HTTPS index host")
        return cls(values["PINECONE_API_KEY"], values["PINECONE_INDEX_NAME"],
                   "https://" + parsed.hostname, values["PINECONE_NAMESPACE"])


def product_url(slug, product_id):
    """Accept a real Lotus URL or build one from a source slug; never guess one."""
    slug = str(slug or "").strip()
    pid = str(product_id or "").strip()
    if not slug or not pid:
        return ""
    if "://" in slug:
        parsed = urlsplit(slug)
        if (parsed.scheme == "https" and parsed.hostname in
                {"lotuselectronics.com", "www.lotuselectronics.com"}
                and not parsed.username and not parsed.password
                and parsed.path.startswith("/product/")):
            return slug
        return ""
    # The live API includes the category prefix, e.g. "iphones/real-phone".
    # Preserve those path segments without permitting traversal or URL syntax.
    if (any(char in slug for char in "\\?#:")
            or any(part in {"", ".", ".."} for part in slug.split("/"))):
        return ""
    return "https://www.lotuselectronics.com/product/{}/{}".format(
        quote(slug, safe="-/"), quote(pid, safe=""))


def connect_index(config):
    """Read-only validation before any query/upsert. Never creates an index."""
    from pinecone import Pinecone
    client = Pinecone(api_key=config.api_key, timeout=15)
    description = client.describe_index(config.name)
    actual_host = description.host.removeprefix("https://").rstrip("/")
    if actual_host != config.host.removeprefix("https://").rstrip("/"):
        raise ValueError("Index name and host do not match")
    if description.dimension != EMBEDDING_DIMENSION or description.metric != "cosine":
        raise ValueError(f"Index must be dense/{EMBEDDING_DIMENSION}/cosine")
    if getattr(description, "vector_type", "dense") != "dense":
        raise ValueError("A dense vector index is required")
    if getattr(description, "embed", None):
        raise ValueError("Use a bring-your-own-vectors index, not integrated embeddings")
    if not description.status.ready:
        raise ValueError("Pinecone index is not ready")
    index = client.Index(host=config.host)
    return index, index.describe_index_stats()
