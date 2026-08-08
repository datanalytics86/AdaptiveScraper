# Adaptive Data Extractor (Tier-1)

Extractor adaptable de datos web: **cualquier URL → CSV + Excel** de calidad.

## Capacidades

| Capacidad | Implementación |
|-----------|----------------|
| Fetch resiliente | `httpx` + retries/backoff + delay |
| JS pesado | Fallback **Playwright** automático |
| Tablas HTML | Filas estructuradas |
| Listados / cards | Heurística de productos |
| Autos (checkeados) | Slugs `/comprar/marca~modelo~año~id` + detalle |
| Precios CLP | Limpieza de `$12.290.000` |
| Dedupe | Por URL + título + precio |
| Export | CSV UTF-8-BOM + XLSX multi-hoja |

## Instalación

```powershell
cd "$env:USERPROFILE\artifacts\AdaptiveScraper"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
playwright install chromium
```

## Uso

```powershell
# Checkeados (default)
python main.py

# URL explícita
python main.py https://www.checkeados.cl/comprar

# Página simple
python main.py https://example.com --no-playwright

# Tablas
python main.py https://www.w3schools.com/html/html_tables.asp --no-playwright

# Forzar Playwright
python main.py https://example.com --playwright

# Solo autos
python main.py https://www.checkeados.cl/comprar --tipo auto
```

Salida en `outputs/`:

- `{dominio}_{timestamp}.csv` / `.xlsx`
- `{dominio}_latest.csv` / `.xlsx`

## Estructura

```
AdaptiveScraper/
├── main.py
├── core/
│   ├── fetcher.py
│   ├── extractor.py
│   ├── cleaner.py
│   └── exporter.py
├── outputs/
├── requirements.txt
├── README.md
└── .gitignore
```

## Disclaimer

Uso responsable. Respeta ToS y `robots.txt`. No abuses de sitios web.
