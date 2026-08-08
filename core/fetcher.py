"""Fetcher resiliente: httpx primero, Playwright como fallback JS."""

from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass

import httpx

logger = logging.getLogger("adaptive_scraper.fetcher")

_UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
]


class FetchError(Exception):
    """Error de red / HTTP controlado."""


@dataclass
class FetchResult:
    url: str
    html: str
    status_code: int
    method: str  # httpx | playwright
    final_url: str


def _headers() -> dict[str, str]:
    return {
        "User-Agent": random.choice(_UA_POOL),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "es-CL,es;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "DNT": "1",
        "Cache-Control": "max-age=0",
    }


def _looks_thin_or_blocked(html: str, status: int) -> bool:
    if status in (401, 403, 429, 503):
        return True
    if len(html) < 1500:
        return True
    low = html[:12000].lower()
    hints = (
        "cf-browser-verification",
        "just a moment",
        "checking your browser",
        "captcha",
        "enable javascript",
        "noscript",
        "__next_f",
    )
    # Next.js con poco HTML visible en body a veces necesita JS; __next_f solo no basta
    if "captcha" in low or "cf-browser" in low:
        return True
    # Muy pocas etiquetas de contenido
    if html.count("<a ") < 3 and html.count("<table") == 0 and "product" not in low:
        if len(html) < 8000:
            return True
    return False


def fetch_httpx(
    url: str,
    *,
    timeout: float = 35.0,
    retries: int = 3,
    delay_range: tuple[float, float] = (0.6, 1.8),
) -> FetchResult:
    last_err: Exception | None = None
    for attempt in range(1, retries + 1):
        time.sleep(random.uniform(*delay_range))
        try:
            with httpx.Client(
                timeout=timeout,
                follow_redirects=True,
                headers=_headers(),
            ) as client:
                r = client.get(url)
                if not r.encoding or r.encoding.lower() in ("iso-8859-1", "ascii"):
                    r.encoding = r.charset_encoding or "utf-8"
                if r.status_code >= 500:
                    raise FetchError(f"HTTP {r.status_code}")
                return FetchResult(
                    url=url,
                    html=r.text,
                    status_code=r.status_code,
                    method="httpx",
                    final_url=str(r.url),
                )
        except Exception as e:  # noqa: BLE001
            last_err = e
            backoff = (2**attempt) + random.uniform(0, 0.5)
            logger.warning("httpx attempt %s failed: %s (backoff %.1fs)", attempt, e, backoff)
            time.sleep(backoff)
    raise FetchError(f"httpx falló tras {retries} intentos: {last_err}")


def fetch_playwright(url: str, *, timeout_ms: int = 45000) -> FetchResult:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        raise FetchError(
            "Playwright no instalado. Ejecuta: pip install playwright && playwright install chromium"
        ) from e

    time.sleep(random.uniform(0.4, 1.0))
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            context = browser.new_context(
                user_agent=random.choice(_UA_POOL),
                locale="es-CL",
                viewport={"width": 1366, "height": 900},
            )
            page = context.new_page()
            resp = page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:  # noqa: BLE001
                pass
            # scroll suave para lazy-load
            for _ in range(3):
                page.mouse.wheel(0, 1200)
                page.wait_for_timeout(400)
            html = page.content()
            status = resp.status if resp else 200
            final = page.url
            context.close()
        finally:
            browser.close()

    return FetchResult(
        url=url,
        html=html,
        status_code=status,
        method="playwright",
        final_url=final,
    )


def fetch_html(
    url: str,
    *,
    force_playwright: bool = False,
    allow_playwright: bool = True,
) -> FetchResult:
    """
    Estrategia:
      1. httpx (rápido)
      2. Si HTML pobre / bloqueado → Playwright (si está permitido)
    """
    if force_playwright and allow_playwright:
        logger.info("Fetch Playwright (forzado): %s", url)
        return fetch_playwright(url)

    result = fetch_httpx(url)
    logger.info(
        "Fetch httpx: status=%s len=%s url=%s",
        result.status_code,
        len(result.html),
        result.final_url,
    )

    if allow_playwright and _looks_thin_or_blocked(result.html, result.status_code):
        logger.info("HTML insuficiente/bloqueado → fallback Playwright")
        try:
            return fetch_playwright(url)
        except FetchError as e:
            logger.warning("Playwright fallback falló: %s — se usa httpx", e)
            return result

    # Sitios de listados de autos con JS: si hay pocos links de producto, intentar PW
    if allow_playwright and _needs_js_enrichment(result.html, url):
        logger.info("Posible contenido JS incompleto → Playwright enrichment")
        try:
            pw = fetch_playwright(url)
            if len(pw.html) > len(result.html) * 0.8:
                return pw
        except FetchError as e:
            logger.warning("Playwright enrichment falló: %s", e)

    return result


def _needs_js_enrichment(html: str, url: str) -> bool:
    """Heurística: listados con pocas cards pero presencia de frameworks JS."""
    low = url.lower()
    if any(x in low for x in ("checkeados", "comprar", "vehicul", "auto")):
        # checkeados entrega mucho HTML por RSC; no forzar siempre
        if html.count("/comprar/") >= 10:
            return False
        return True
    if "__NEXT_DATA__" in html or "self.__next_f" in html:
        # Si casi no hay precios en el HTML estático
        if html.count("$") < 5 and html.count("price") < 3:
            return True
    return False
