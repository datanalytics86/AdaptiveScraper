"""Exportación CSV + Excel con nombres dominio_timestamp."""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import pandas as pd

logger = logging.getLogger("adaptive_scraper.exporter")


def _domain_slug(url: str) -> str:
    host = urlparse(url).netloc.replace("www.", "") or "site"
    return re.sub(r"[^\w.\-]+", "_", host)


def records_to_dataframe(records: list[dict[str, Any]]) -> pd.DataFrame:
    if not records:
        return pd.DataFrame()
    df = pd.DataFrame(records)
    preferred = [
        "tipo",
        "titulo",
        "marca",
        "modelo",
        "anio",
        "precio_clp",
        "precio_lista_clp",
        "precio",
        "kilometros",
        "ubicacion",
        "color",
        "url",
        "categoria",
        "texto",
        "fuente_dominio",
        "fuente_url",
        "id_externo",
    ]
    cols = [c for c in preferred if c in df.columns] + [
        c for c in df.columns if c not in preferred
    ]
    return df[cols]


def export_records(
    records: list[dict[str, Any]],
    source_url: str,
    output_dir: str | Path,
    prefix: str | None = None,
) -> dict[str, Path]:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    slug = prefix or _domain_slug(source_url)
    base = out / f"{slug}_{ts}"

    df = records_to_dataframe(records)
    paths: dict[str, Path] = {}

    if df.empty:
        logger.warning("No hay filas para exportar")
        return paths

    csv_path = Path(f"{base}.csv")
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    paths["csv"] = csv_path

    xlsx_path = Path(f"{base}.xlsx")
    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="datos")
        summary_rows = [
            {"metric": "total_filas", "value": len(df)},
            {"metric": "columnas", "value": len(df.columns)},
            {"metric": "fuente", "value": source_url},
        ]
        if "tipo" in df.columns:
            for t, n in df["tipo"].value_counts().items():
                summary_rows.append({"metric": f"tipo:{t}", "value": int(n)})
        if "precio_clp" in df.columns:
            summary_rows.append(
                {
                    "metric": "con_precio_clp",
                    "value": int(df["precio_clp"].notna().sum()),
                }
            )
        pd.DataFrame(summary_rows).to_excel(writer, index=False, sheet_name="resumen")
        if "tipo" in df.columns and df["tipo"].nunique() > 1:
            for tipo, g in df.groupby("tipo"):
                sheet = re.sub(r"[\\/*?:\[\]]", "_", str(tipo))[:28] or "otros"
                g.to_excel(writer, index=False, sheet_name=sheet)
    paths["xlsx"] = xlsx_path

    # latest aliases
    latest = out / f"{slug}_latest"
    df.to_csv(Path(f"{latest}.csv"), index=False, encoding="utf-8-sig")
    df.to_excel(Path(f"{latest}.xlsx"), index=False, engine="openpyxl")
    paths["csv_latest"] = Path(f"{latest}.csv")
    paths["xlsx_latest"] = Path(f"{latest}.xlsx")

    logger.info("Exported %s rows → %s", len(df), csv_path)
    return paths
