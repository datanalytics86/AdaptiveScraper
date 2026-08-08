#!/usr/bin/env python3
"""
Adaptive Data Extractor — CLI Tier-1
URL → extracción adaptable → CSV + Excel

Uso:
  python main.py https://www.checkeados.cl/comprar
  python main.py https://example.com --no-playwright
  python main.py https://www.w3schools.com/html/html_tables.asp
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from urllib.parse import urlparse

from core.cleaner import clean_records
from core.exporter import export_records
from core.extractor import extract_records
from core.fetcher import FetchError, fetch_html

ROOT = Path(__file__).resolve().parent
DEFAULT_OUT = ROOT / "outputs"


def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)-7s | %(message)s",
        datefmt="%H:%M:%S",
    )


def valid_url(url: str) -> bool:
    try:
        p = urlparse(url.strip())
        return p.scheme in ("http", "https") and bool(p.netloc)
    except Exception:  # noqa: BLE001
        return False


def run(
    url: str,
    *,
    output_dir: Path,
    force_playwright: bool = False,
    no_playwright: bool = False,
    filter_tipo: str | None = None,
) -> int:
    log = logging.getLogger("adaptive_scraper")
    url = url.strip()
    if not valid_url(url):
        log.error("URL inválida: %s", url)
        return 2

    log.info("▶ Fetch: %s", url)
    try:
        result = fetch_html(
            url,
            force_playwright=force_playwright,
            allow_playwright=not no_playwright,
        )
    except FetchError as e:
        log.error("Fetch falló: %s", e)
        return 1

    log.info(
        "✓ HTML %s bytes via %s (HTTP %s)",
        f"{len(result.html):,}",
        result.method,
        result.status_code,
    )

    raw = extract_records(result.html, result.final_url)
    records = clean_records(raw, result.final_url)

    if filter_tipo:
        records = [r for r in records if str(r.get("tipo", "")).lower() == filter_tipo.lower()]

    if not records:
        log.error("No se extrajeron registros útiles")
        return 1

    # Para checkeados / autos: priorizar tipo auto en export principal si hay muchos
    autos = [r for r in records if r.get("tipo") == "auto"]
    export_set = autos if len(autos) >= 3 else records

    paths = export_records(export_set, result.final_url, output_dir)
    log.info("✓ %s registros exportados", len(export_set))
    for kind, path in paths.items():
        log.info("  %s → %s", kind, path)

    # Vista rápida
    try:
        import pandas as pd

        df = pd.DataFrame(export_set)
        cols = [
            c
            for c in (
                "tipo",
                "titulo",
                "marca",
                "modelo",
                "anio",
                "precio_clp",
                "kilometros",
                "ubicacion",
            )
            if c in df.columns
        ]
        if cols:
            print("\n── Vista previa ──")
            print(df[cols].head(12).to_string(index=False))
    except Exception:  # noqa: BLE001
        pass

    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Adaptive Data Extractor Tier-1 — URL → CSV/Excel",
    )
    parser.add_argument(
        "url",
        nargs="?",
        default="https://www.checkeados.cl/comprar",
        help="URL a extraer (default: checkeados.cl/comprar)",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=str(DEFAULT_OUT),
        help="Directorio de salida",
    )
    parser.add_argument(
        "--playwright",
        action="store_true",
        help="Forzar Playwright",
    )
    parser.add_argument(
        "--no-playwright",
        action="store_true",
        help="Deshabilitar fallback Playwright",
    )
    parser.add_argument(
        "--tipo",
        default=None,
        help="Filtrar por tipo (auto, tabla, enlace, ...)",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    setup_logging(args.verbose)
    return run(
        args.url,
        output_dir=Path(args.output),
        force_playwright=args.playwright,
        no_playwright=args.no_playwright,
        filter_tipo=args.tipo,
    )


if __name__ == "__main__":
    sys.exit(main())
