# 03 — ETL, Cleaning Rules and Reconciliation

## 1. Tool choice: Python (pandas + openpyxl + psycopg2)

| Criterion | Python | Power Query | Pure SQL |
|---|---|---|---|
| Reads the `.xlsm` without running macros | ✔ (`openpyxl`, read-only, cached values) | ✔ | ✘ (needs a previous load) |
| Runs in a container, reproducible with one command | ✔ | ✘ (tied to Power BI Desktop / Windows) | ✔ |
| Versionable as plain text, reviewable in Git | ✔ | partly (M inside the PBIP) | ✔ |
| Unpivot of 18 column pairs, regex normalization, hashing for pseudonyms | ✔ native | possible, verbose | possible, verbose |
| Logs every rule with counts in the database | ✔ | ✘ | ✔ |

Power Query would put the business rules **inside the report**: Grafana would not see them, and the warehouse would stop being the single source of truth. That is why we chose Python. PostgreSQL does what it does best: it generates the calendar, checks the constraints and computes the KPI views.

## 2. Pipeline (`etl/etl/main.py`, full refresh, idempotent)

```
Excel (.xlsm) ──► 1 extract tables by name (T_baseDeDatos, Tabla2, Tabla8/14/15/16, Sin_programación, Tabla9/10)
              ──► 2 pseudonymize people (before anything is written)
              ──► 3 clean: R02–R11
              ──► 4 transform: unpivot stoppages (R12–R13), link complements (R14), OEE time model (R15–R17)
              ──► 5 load: stg.* (raw, text) → dim_* → fact_* (COPY, one transaction)
              ──► 6 reconcile source vs warehouse → etl.reconciliacion
```

- **From scratch:** `docker compose down -v && docker compose up -d --build` creates the schema (`sql/init`), runs the ETL and starts the services.
- **Re-run only the ETL:** `docker compose run --rm etl`. The tables are truncated and reloaded in a single transaction, so a failed run leaves the previous load intact and is stored as `FAILED` in `etl.run_log`.
- Each run saves the source file's SHA-256 in `etl.run_log`, which proves which version of the Excel was loaded.

## 3. Cleaning rules and their effect (run over the delivered Excel)

| Rule | DQ | Rule | Before | Affected | After | Action |
|---|---|---|---:|---:|---:|---|
| R01 | DQ14 | Pseudonymize names | 8,208 | 5,709 | 8,208 | Name → `PER-xxxxxx` (SHA-256 + salt from `.env`) |
| R02 | — | Type conversion (numbers, date) | 8,208 | 0 | 8,208 | Non-numeric text → NULL; invalid dates discarded |
| R03 | DQ8 | Exact duplicates | 8,208 | 42 | 8,166 | Keep the first occurrence |
| R04 | DQ10 | 100% empty columns | 8,166 | 0 | 8,166 | Drop `Unidades producidas cada minuto` and `Display por paca` |
| R05 | DQ2 | Shift repeated in `Unidad por display` | 8,166 | 676 | 8,166 | Redundant column used as fallback, then dropped; aliases unified |
| R06 | DQ1 | Missing shift | 8,166 | 3,892 | 8,166 | SK −1 *No registrado* |
| R07 | DQ3 | Two coding schemes in `Tipo de paro` | 8,166 | 1,460 | 8,166 | Old and new schemes → 12 unified statuses |
| R08 | DQ7 | Reference typos | 8,166 | 505 | 8,166 | 52 distinct values → 49 |
| R09 | DQ12 | Missing reference | 8,166 | 3,855 | 8,166 | SK −1 *No registrada* |
| R10 | DQ11 | Placeholder or missing operator | 8,166 | 4,236 | 8,166 | 532 → SK 0, 3,704 → SK −1 |
| R11 | DQ5 | Record type | 8,166 | 223 | 7,943 | PRODUCCION 5,137 · NO_PROGRAMADO 1,460 · COMPLEMENTO 1,346 · empty rows removed 223 |
| R12 | DQ4/DQ15 | Subcodes of 01/03/05 | 3,691 | 940 | 3,691 | 940 old `4.x` renumbered to `5.x`; 3,584 exact; 107 without subcode; 0 unrecognized |
| R13 | — | Unpivot of 18 code columns | 7,943 | 16,482 | 16,482 | One row per cause with duration > 0 |
| R14 | DQ5 | Link complements to their form | 1,346 | 1,317 | 1,346 | 1,294 strict key + 23 relaxed key; 29 without a parent |
| R15 | DQ9 | Stoppage > hours worked | 6,597 | 48 | 6,597 | Flag; derived hours floored at 0 |
| R16 | DQ12 | Ideal rate cannot be computed | 5,137 | 2,308 | 5,137 | Left out of Performance (4 rows used another machine's units per bale) |
| R17 | DQ6 | Outliers (> 1.5 × ideal shift output) | 5,137 | 15 | 5,137 | Excluded **only** from Performance |

The same table is available live in `etl.dq_log` (query in `sql/queries/02_reconciliation.sql`).

**Strict vs relaxed key (R14).** Strict = date + machine + shift + operator + reference. Relaxed = date + machine + operator, used when the complement was typed with a different reference or shift. The 29 complements without a parent keep their stoppage in `fact_paro` (Pareto, MTTR); they only stay out of the per-form OEE.

**Outlier threshold (R17).** A shift cannot produce more than its ideal output (`hours × ideal bales/h`). 1.5× leaves room for catalog errors (e.g. Vinilos_3 runs at ≈ 100%) and still catches the 4,000–9,417-bale records, which look like units typed as bales. When the reference is unknown, the fastest reference of that machine is used as the ceiling.

## 4. Reconciliation (source vs warehouse)

| Metric | Source | Loaded | Difference | Explanation |
|---|---:|---:|---:|---|
| Rows | 8,208 | 7,943 | −265 | 6,597 forms + 1,346 complements; −42 duplicates − 223 empty rows |
| Hours worked | 38,063.35 | 37,934.35 | −129.00 | Hours of the removed duplicates |
| Bales produced | 378,778 | 377,708 | −1,070 | Bales of the duplicates. The 15 outliers (53,248 bales) are **kept** |
| Non-scheduled hours | 41,519.85 | 41,343.85 | −176.00 | Duplicates |
| Stoppage time (`fact_paro`) | 8,449.65 | 8,431.54 | −18.11 | Duplicates (18.12 h; ±0.01 h from rounding) |
| Stoppage time (per form) | 8,449.65 | 8,395.59 | −54.06 | Duplicates + 35.95 h of the 29 complements without a parent |

**Independent check:** `sql/queries/02_reconciliation.sql`, query 4, takes the 265 rows in `stg.base_datos_raw` that reached no fact table. They add up to **129.00 h, 1,070 bales and 18.12 h of stoppage**, exactly the differences shown above. Every difference is explained.

## 5. What the warehouse stores but the Excel did not

- The record type, the parent form of each complement and the OEE class of each code.
- The ideal output per shift (machine speed × reference) and the run time.
- Flags for outliers, stoppages exceeding the shift and rows valid for Performance.
- The lineage key `registro_id` = Excel row, so any figure can be traced back to its source cell.
