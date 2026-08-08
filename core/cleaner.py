"""Limpieza y normalización de datos (precios CLP, texto, dedupe)."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

_RE_NON_DIGIT = re.compile(r"[^\d]")
_RE_WS = re.compile(r"\s+")


def clean_price_clp(value: Any) -> float | None:
    """
    Parsea precios chilenos: $12.290.000 | 12.290.000 | UF 3.500.
    Devuelve float en la unidad detectada (CLP o UF según contexto del raw).
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if not s:
        return None
    # Quitar moneda y espacios
    s = s.replace("\xa0", " ")
    s = re.sub(r"(?i)\b(clp|usd|uf|pesos?)\b", "", s)
    s = s.replace("$", "").replace("€", "").strip()
    # Miles con punto / decimal con coma
    if "." in s and "," in s:
        s = s.replace(".", "").replace(",", ".")
    elif s.count(".") > 1:
        s = s.replace(".", "")
    elif s.count(".") == 1:
        left, right = s.split(".")
        if len(right) == 3 and left.isdigit():
            s = left + right
    elif "," in s:
        parts = s.split(",")
        if len(parts[-1]) <= 2:
            s = s.replace(",", ".")
        else:
            s = s.replace(",", "")
    s = _RE_NON_DIGIT.sub("", s) if re.fullmatch(r"[\d\s.]+", s.replace(",", "")) is None else s
    # Si quedó solo dígitos tras limpieza agresiva
    digits = _RE_NON_DIGIT.sub("", str(value))
    # Preferir reconstrucción desde dígitos cuando hay formato $x.xxx.xxx
    if re.search(r"\d{1,3}(\.\d{3})+", str(value)):
        digits = _RE_NON_DIGIT.sub("", str(value).split(",")[0])
    try:
        if digits:
            return float(digits)
        return float(s) if s else None
    except ValueError:
        try:
            return float(digits) if digits else None
        except ValueError:
            return None


def clean_text(value: Any, max_len: int = 2000) -> str | None:
    if value is None:
        return None
    t = _RE_WS.sub(" ", str(value)).strip()
    if not t:
        return None
    return t[:max_len]


def clean_kilometers(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    s = str(value).lower().replace("km", "").replace(" ", "")
    n = clean_price_clp(s)
    return int(n) if n is not None else None


def clean_year(value: Any) -> int | None:
    if value is None:
        return None
    try:
        y = int(float(str(value).strip()))
        return y if 1950 <= y <= 2100 else None
    except (TypeError, ValueError):
        m = re.search(r"\b(19[5-9]\d|20[0-3]\d)\b", str(value))
        return int(m.group(1)) if m else None


def _fingerprint(rec: dict[str, Any]) -> str:
    url = (rec.get("url") or "").split("?")[0].rstrip("/")
    title = (rec.get("titulo") or rec.get("texto") or "").lower()[:80]
    price = rec.get("precio_clp") or rec.get("precio") or ""
    return f"{url}|{title}|{price}"


def clean_records(records: list[dict[str, Any]], source_url: str) -> list[dict[str, Any]]:
    """Normaliza campos, deduplica y añade metadatos de fuente."""
    domain = urlparse(source_url).netloc.replace("www.", "")
    cleaned: list[dict[str, Any]] = []
    seen: set[str] = set()

    for raw in records:
        rec = dict(raw)
        # Precios
        for key in ("precio_clp", "precio", "precio_lista_clp", "ahorro_clp"):
            if key in rec and rec[key] is not None:
                rec[key] = clean_price_clp(rec[key])
        if rec.get("precio") and not rec.get("precio_clp"):
            rec["precio_clp"] = rec["precio"]

        if "kilometros" in rec:
            rec["kilometros"] = clean_kilometers(rec["kilometros"])
        if "anio" in rec:
            rec["anio"] = clean_year(rec["anio"])

        for key in ("titulo", "texto", "marca", "modelo", "ubicacion", "color", "categoria"):
            if key in rec:
                rec[key] = clean_text(rec[key])

        rec["fuente_dominio"] = domain
        rec["fuente_url"] = source_url

        # Descartar filas vacías
        meaningful = any(
            rec.get(k)
            for k in (
                "titulo",
                "texto",
                "url",
                "precio_clp",
                "marca",
                "modelo",
            )
        )
        if not meaningful:
            continue

        fp = _fingerprint(rec)
        if fp in seen:
            continue
        seen.add(fp)
        cleaned.append(rec)

    return cleaned
