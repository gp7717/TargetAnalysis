"""
Shared data loading and style-text building for gap analysis and ingest.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

# CLIP context is 77 tokens; keep style text within ~500 chars
MAX_STYLE_CHARS = 500


def load_products(path: Path | str) -> list[dict]:
    """Load products from JSON, JSONL, or CSV. Path can be Path or str."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Input file not found: {path}")

    suffix = path.suffix.lower()
    if suffix == ".json":
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and "products" in data:
            return data["products"]
        return [data]
    if suffix == ".jsonl":
        products = []
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                products.append(json.loads(line))
        return products
    if suffix == ".csv":
        with open(path, encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            return list(reader)
    raise ValueError(f"Unsupported format: {suffix}. Use .json, .jsonl, or .csv")


def safe_str(v: object) -> str:
    """Coerce value to string for document/metadata."""
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v).strip()


def build_style_text(product: dict) -> str:
    """
    Build style + function string for embedding: title | brand | category_breadcrumb | colors.
    Optional later: append description, highlights, material_text.
    Normalize: strip, collapse whitespace. Always return non-empty when title or brand exists.
    """
    parts = [
        safe_str(product.get("title") or ""),
        safe_str(product.get("brand") or ""),
        safe_str(product.get("category_breadcrumb") or ""),
        safe_str(product.get("colors") or ""),
    ]
    # Join with " | ", drop empty segments, then rejoin so we don't end with " | "
    text = " | ".join(p for p in parts if p)
    # Collapse whitespace
    text = " ".join(text.split())
    if len(text) > MAX_STYLE_CHARS:
        text = text[:MAX_STYLE_CHARS].rsplit(" ", 1)[0] or text[:MAX_STYLE_CHARS]
    return text.strip() or " "
