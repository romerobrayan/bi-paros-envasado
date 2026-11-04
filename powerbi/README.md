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

- Source: **PostgreSQL database** `localhost:5432`, database `bi_paros`, user `powerbi_ro` (read-only on schema `dw`). Do not connect to the Excel.
- Mode: Import (the dataset is small; Import enables full DAX time intelligence).
- Tables to import: `dw.dim_*` and `dw.fact_produccion_turno`, `dw.fact_paro`.

The semantic model, the DAX measures and the report pages are built in the next stage of the workshop.
