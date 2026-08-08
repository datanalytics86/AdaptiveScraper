"""Extractor adaptable: tablas, cards, listados, heurísticas (autos/productos)."""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag

logger = logging.getLogger("adaptive_scraper.extractor")

_RE_PRICE = re.compile(
    r"\$\s*[\d.]+(?:\.\d{3})*(?:,\d+)?|\b\d{1,3}(?:\.\d{3})+\b|\bUF\s*[\d.,]+",
    re.I,
)
_RE_KM = re.compile(r"([\d.]+)\s*km\b", re.I)
_RE_YEAR = re.compile(r"\b(19[5-9]\d|20[0-3]\d)\b")
_RE_AUTO_SLUG = re.compile(
    r"/comprar/([a-z0-9\-]+)~([a-z0-9\-]+)~(\d{4})~([a-f0-9]+)",
    re.I,
)


def extract_records(html: str, base_url: str) -> list[dict[str, Any]]:
    """Orquesta estrategias y devuelve lista de dicts homogéneos."""
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript", "svg"]):
        # Conservamos JSON-LD antes de borrar scripts
        pass

    # Extraer JSON-LD antes de descomponer scripts
    json_ld_rows = _extract_json_ld(soup, base_url)

    for tag in soup(["script", "style", "noscript", "svg", "iframe"]):
        tag.decompose()

    rows: list[dict[str, Any]] = []
    rows.extend(json_ld_rows)
    rows.extend(_extract_tables(soup, base_url))
    rows.extend(_extract_auto_listings(soup, html, base_url))
    rows.extend(_extract_product_cards(soup, base_url))
    rows.extend(_extract_links(soup, base_url))
    rows.extend(_extract_headings_paragraphs(soup, base_url))

    if not rows:
        rows.extend(_extract_fallback_text(soup, base_url))

    logger.info("Extracted %s raw rows from %s", len(rows), base_url)
    return rows


def _extract_json_ld(soup: BeautifulSoup, base_url: str) -> list[dict[str, Any]]:
    import json

    rows: list[dict[str, Any]] = []
    for script in soup.find_all("script", type="application/ld+json"):
        raw = script.string or ""
        if not raw.strip():
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        nodes = data if isinstance(data, list) else [data]
        if isinstance(data, dict) and "@graph" in data:
            nodes = data["@graph"]
        for node in nodes:
            if not isinstance(node, dict):
                continue
            t = str(node.get("@type", "")).lower()
            if t in ("product", "car", "vehicle") or "offers" in node:
                name = node.get("name") or node.get("title")
                offers = node.get("offers") or {}
                if isinstance(offers, list):
                    offers = offers[0] if offers else {}
                price = offers.get("price") if isinstance(offers, dict) else None
                url = node.get("url") or (offers.get("url") if isinstance(offers, dict) else None)
                rows.append(
                    {
                        "tipo": "producto",
                        "titulo": name,
                        "precio": price,
                        "url": urljoin(base_url, str(url)) if url else base_url,
                        "categoria": t or "json-ld",
                    }
                )
            elif t == "itemlist":
                for el in node.get("itemListElement") or []:
                    item = el.get("item", el) if isinstance(el, dict) else {}
                    if isinstance(item, dict) and item.get("name"):
                        rows.append(
                            {
                                "tipo": "producto",
                                "titulo": item.get("name"),
                                "url": urljoin(base_url, str(item.get("url") or base_url)),
                                "categoria": "itemlist",
                            }
                        )
    return rows


def _extract_tables(soup: BeautifulSoup, base_url: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for t_idx, table in enumerate(soup.find_all("table"), start=1):
        headers = [
            th.get_text(" ", strip=True) or f"col_{j}"
            for j, th in enumerate(table.find_all("th"), start=1)
        ]
        for r_idx, tr in enumerate(table.find_all("tr"), start=1):
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
            if not any(cells):
                continue
            # Fila como registro aplanado
            rec: dict[str, Any] = {
                "tipo": "tabla",
                "tabla_id": t_idx,
                "fila": r_idx,
                "url": base_url,
            }
            for c_idx, cell in enumerate(cells):
                col = headers[c_idx] if c_idx < len(headers) else f"col_{c_idx + 1}"
                # slug column name
                key = re.sub(r"\W+", "_", col.lower()).strip("_")[:40] or f"col_{c_idx}"
                rec[key] = cell
                if _RE_PRICE.search(cell) and "precio" not in rec:
                    rec["precio"] = cell
            rec["titulo"] = cells[0] if cells else None
            rec["texto"] = " | ".join(cells)
            rows.append(rec)
    return rows


def _extract_auto_listings(
    soup: BeautifulSoup, html: str, base_url: str
) -> list[dict[str, Any]]:
    """Listados tipo checkeados (/comprar/marca~modelo~anio~id) y cards con km/precio."""
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()

    for a in soup.find_all("a", href=True):
        href = a["href"]
        m = _RE_AUTO_SLUG.search(href)
        if not m:
            continue
        full = urljoin(base_url, href).split("?")[0]
        if full in seen:
            continue
        seen.add(full)
        brand, model, year, vid = m.groups()

        # Texto de tarjeta: li/article padre compacto
        card = a.find_parent("li") or a.find_parent("article")
        text = ""
        if card:
            text = card.get_text(" ", strip=True)
        if len(text) < 40:
            text = a.get_text(" ", strip=True)
        # Ventana HTML alrededor del slug
        if len(text) < 80 or not _RE_PRICE.search(text):
            idx = html.find(href) if href in html else html.find(m.group(0))
            if idx >= 0:
                chunk = re.sub(r"<[^>]+>", " ", html[max(0, idx - 200) : idx + 1600])
                chunk = re.sub(r"\s+", " ", chunk).strip()
                if len(chunk) > len(text):
                    text = chunk

        # Ignorar basura de payloads RSC embebidos
        if "self.__next_f" in text or "\"children\"" in text[:80]:
            text = a.get_text(" ", strip=True) or f"{brand} {model} {year}"

        prices = [_p for _p in (_price_num(x) for x in _RE_PRICE.findall(text)) if _p]
        # Solo precios de vehículo reales (>= 3M CLP). "Ahorras $500.000" no cuenta.
        altos = [p for p in prices if 3_000_000 <= p <= 250_000_000]
        precio = min(altos) if altos else None
        precio_lista = max(altos) if len(set(altos)) > 1 else None

        km_m = _RE_KM.search(text)
        ubic = None
        um = re.search(r"Disponible en\s+([^$·\n]+)", text, re.I)
        if um:
            ubic = um.group(1).strip()

        color = None
        cm = re.search(r"·\s*([a-záéíóúñü\s]+?)(?:\s+Con|\s+Disponible|\s*\$)", text, re.I)
        if cm:
            color = cm.group(1).strip().title()

        rows.append(
            {
                "tipo": "auto",
                "marca": brand.replace("-", " ").title(),
                "modelo": model.replace("-", " ").title(),
                "anio": int(year),
                "precio_clp": precio,
                "precio_lista_clp": precio_lista,
                "kilometros": km_m.group(1) if km_m else None,
                "ubicacion": ubic,
                "color": color,
                "url": full,
                "id_externo": vid,
                "titulo": text[:200] if text else f"{brand} {model} {year}",
                "categoria": "vehiculo",
            }
        )

    # Checkeados: el listado SSR suele traer fichas incompletas → enriquecer detalle
    if rows and "checkeados" in base_url.lower():
        need = [
            r
            for r in rows
            if not r.get("precio_clp")
            or not r.get("kilometros")
            or (r.get("precio_clp") or 0) < 3_000_000
        ]
        if need:
            logger.info("Enriqueciendo %s/%s fichas checkeados vía detalle", len(need), len(rows))
            rows = _enrich_checkeados_details(rows, base_url, limit=min(40, len(rows)))

    return rows


def _enrich_checkeados_details(
    rows: list[dict[str, Any]], base_url: str, limit: int = 25
) -> list[dict[str, Any]]:
    """Enriquece fichas checkeados visitando detalle (httpx)."""
    from .fetcher import fetch_httpx

    out: list[dict[str, Any]] = []
    for i, rec in enumerate(rows):
        if i >= limit:
            out.append(rec)
            continue
        url = rec.get("url")
        if not url:
            out.append(rec)
            continue
        try:
            fr = fetch_httpx(url, retries=2, delay_range=(0.5, 1.2))
            soup = BeautifulSoup(fr.html, "lxml")
            text = soup.get_text("\n", strip=True)
            prices = [
                p
                for p in (_price_num(x) for x in _RE_PRICE.findall(text))
                if p and 3_000_000 <= p <= 250_000_000
            ]
            if prices:
                rec = dict(rec)
                rec["precio_clp"] = min(prices)
                if len(set(prices)) > 1:
                    rec["precio_lista_clp"] = max(prices)
            kms = _RE_KM.findall(text)
            for km in kms:
                n = _price_num(km)
                if n and n >= 500:
                    rec["kilometros"] = int(n)
                    break
            h1 = soup.find("h1")
            if h1:
                rec["titulo"] = h1.get_text(" ", strip=True)
            for line in text.splitlines():
                if "Las Condes" in line or "Huechuraba" in line:
                    if len(line) < 100:
                        rec["ubicacion"] = line.strip(" ·,")
                        break
            logger.debug("Enriched %s price=%s", url, rec.get("precio_clp"))
        except Exception as e:  # noqa: BLE001
            logger.warning("Detail enrich failed %s: %s", url, e)
        out.append(rec)
    return out


def _price_num(raw: str) -> float | None:
    from .cleaner import clean_price_clp

    return clean_price_clp(raw)


def _extract_product_cards(soup: BeautifulSoup, base_url: str) -> list[dict[str, Any]]:
    """Heurística genérica de cards de producto."""
    rows: list[dict[str, Any]] = []
    selectors = [
        "article",
        "li.product",
        "div.product",
        "div.card",
        "[class*='product-card']",
        "[class*='ProductCard']",
        "li.ui-search-layout__item",
        "div.ui-search-result",
    ]
    seen_titles: set[str] = set()
    for sel in selectors:
        for card in soup.select(sel):
            if not isinstance(card, Tag):
                continue
            text = card.get_text(" ", strip=True)
            if len(text) < 15 or len(text) > 1500:
                continue
            title_el = card.find(["h1", "h2", "h3", "h4"]) or card.find("a")
            title = title_el.get_text(" ", strip=True) if title_el else None
            if not title or title.lower() in seen_titles:
                continue
            link = card.find("a", href=True)
            href = urljoin(base_url, link["href"]) if link else base_url
            price_m = _RE_PRICE.search(text)
            # evitar nav/footer
            if title.lower() in ("comprar", "vender", "menú", "menu", "inicio"):
                continue
            seen_titles.add(title.lower())
            rows.append(
                {
                    "tipo": "card",
                    "titulo": title[:300],
                    "precio": price_m.group(0) if price_m else None,
                    "url": href,
                    "texto": text[:400],
                    "categoria": "producto_card",
                }
            )
            if len(rows) >= 80:
                return rows
    return rows


def _extract_links(soup: BeautifulSoup, base_url: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for i, a in enumerate(soup.find_all("a", href=True), 1):
        href = urljoin(base_url, a["href"])
        if href.startswith(("javascript:", "mailto:", "tel:", "#")):
            continue
        if href in seen:
            continue
        text = a.get_text(" ", strip=True)
        if not text or len(text) < 2:
            continue
        seen.add(href)
        rows.append(
            {
                "tipo": "enlace",
                "titulo": text[:300],
                "url": href,
                "texto": text[:300],
                "categoria": "link",
            }
        )
        if i > 200:
            break
    return rows


def _extract_headings_paragraphs(soup: BeautifulSoup, base_url: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for level in ("h1", "h2", "h3"):
        for i, el in enumerate(soup.find_all(level), 1):
            t = el.get_text(" ", strip=True)
            if t:
                rows.append(
                    {
                        "tipo": "titulo",
                        "titulo": t,
                        "campo": f"{level}_{i}",
                        "url": base_url,
                        "categoria": level,
                    }
                )
    root = soup.select_one("main, article, [role='main']") or soup.body or soup
    for i, p in enumerate(root.find_all("p"), 1):
        t = p.get_text(" ", strip=True)
        if len(t) < 40:
            continue
        rows.append(
            {
                "tipo": "parrafo",
                "texto": t[:2000],
                "titulo": t[:80],
                "url": base_url,
                "categoria": "contenido",
            }
        )
        if i >= 40:
            break
    return rows


def _extract_fallback_text(soup: BeautifulSoup, base_url: str) -> list[dict[str, Any]]:
    text = soup.get_text("\n", strip=True)
    rows = []
    for i, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if len(line) < 4:
            continue
        rows.append(
            {
                "tipo": "texto",
                "texto": line[:2000],
                "titulo": line[:80],
                "url": base_url,
                "categoria": "fallback",
            }
        )
        if i >= 100:
            break
    return rows
