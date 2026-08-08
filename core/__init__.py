"""AdaptiveScraper core package."""

from .cleaner import clean_records
from .exporter import export_records
from .extractor import extract_records
from .fetcher import fetch_html

__all__ = ["clean_records", "export_records", "extract_records", "fetch_html"]
