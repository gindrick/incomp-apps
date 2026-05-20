from __future__ import annotations

import hashlib
from pathlib import Path


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def compute_documents_hash(hashes: list[str]) -> str:
    combined = "".join(sorted(hashes))
    return hashlib.sha256(combined.encode()).hexdigest()
