# Power BI project

## Format: PBIP (Power BI Project) with TMDL

Save the report with *File → Save as → Power BI Project (*.pbip)* and enable the preview options **"Store semantic model using TMDL format"** and **"Store reports using enhanced metadata format (PBIR)"**.

Why PBIP and not `.pbix`:

| | `.pbix` | `.pbip` + TMDL/PBIR |
|---|---|---|
| Content | one binary zip | folders of text files (one `.tmdl` file per table, measures included) |
| `git diff` | unreadable | shows exactly which measure or relationship changed |
| Merge / review | impossible | line by line, like code |
| Data cached in the file | yes (and personal data with it) | no: `cache.abf` is git-ignored |

## Connection

- Source: **PostgreSQL database** `localhost:5433` (the `DB_PORT` published by Docker), database `bi_paros`, user `powerbi_ro` (read-only on schema `dw`). It never connects to the Excel.
- Mode: Import (the dataset is small; Import enables full DAX time intelligence).
- Tables: `dw.dim_*`, `dw.fact_produccion_turno`, `dw.fact_paro`.

## Open it after cloning

1. Start the server side (`docker compose up -d --build`, see the main README).
2. Open `BI_Paros_Envasado.pbip`. When asked, choose **Base de datos**, user `powerbi_ro`, password `POWERBI_DB_PASSWORD` from `.env`.
3. **Inicio → Actualizar**. The data cache (`.pbi/cache.abf`) is not versioned, so the visuals are empty until the first refresh.

## Contents

- `BI_Paros_Envasado.SemanticModel/definition/` — TMDL: one file per table, the relationships and the `_Medidas` table (38 measures in display folders).
- `BI_Paros_Envasado.Report/definition/pages/` — PBIR: 4 pages (Resumen ejecutivo, Análisis de paros, Mantenimiento, Producción y planeación).
- `medidas.dax` — the same measures for the DAX query view; `build_report_pages.py` — generator of the first version of the pages.
- Step-by-step guide: [docs/04-powerbi-guide.md](../docs/04-powerbi-guide.md).
