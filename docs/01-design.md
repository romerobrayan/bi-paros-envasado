# 01 — Solution Design: Stoppage & Productivity BI for the Packaging Lines

> Status: **approved v1.1** (decisions of §8 closed on 2026-11-04). Figures come from the ETL run over `SEGUIMIENTO TEMPERAS Y VINILOS Actividad.xlsm`.

---

## 1. Users and business questions

| User | Layer | Refresh cadence | Business questions |
|---|---|---|---|
| **Senior management / monthly committee** | Power BI | Monthly | Q1. How does OEE evolve by machine, month and year? Is 2025 better than 2024? <br> Q2. Which stoppage causes concentrate 80% of the lost time (Pareto)? <br> Q3. Which line deserves the next investment? |
| **Maintenance coordinator** (owner of P-MTO-22) | Power BI + Grafana | Daily / monthly | Q4. Which system and component fails most (code 01 → system → component)? <br> Q5. MTBF and MTTR per machine <br> Q6. Time lost to power-supply issues (03) and operational adjustments (05) |
| **Production supervisor** | Grafana | Near real time (hourly) | Q7. Which machine is stopped or below target **right now**? <br> Q8. How is the current shift doing against the hourly target? <br> Q9. Did any line fall below the OEE threshold in the last hours? |
| **Production planning** | Power BI | Monthly | Q10. How much capacity is lost to non-scheduled shifts (sales/planning)? <br> Q11. Which references (SKU) and shifts perform worst? |

---

## 2. Source diagnosis

**Structure.** `T_baseDeDatos` (sheet *Base De Datos*): 8,208 rows × 58 columns, 2022-01-01 → 2025-03-28, 4 machines. It is a **wide** table: one row per data-entry form with 18 pairs of "Code N (minutes) / Code N in hours" columns. Catalogs live in *Tablas Desplegables*: stoppage codes (Tabla2), subcodes of codes 01/03/05 (Sin_programación, Tabla9, Tabla10), shifts (Tabla18), agents (Tabla12) and the **ideal-rate catalog per machine × reference** (Tabla8/14/15/16: units per minute and units per bale). The sheet *Base de datos de Sub codigos* (1,252 rows, Oct-2023 → May-2024) is a partial copy of the subcode columns of the main table; it is **not loaded** to avoid double counting.

The Excel writes three kinds of rows into the same table (discovered while profiling):

| Record type | How it is recognized | Rows (after dedup) |
|---|---|---|
| Production form ("Ingreso total") | `Horas trabajadas` informed | 5,137 |
| Non-scheduled shift | no hours worked, `Horas no trabajadas` informed + reason in `Tipo de paro` | 1,460 |
| Complement ("Ingreso subcódigo") | no hours at all, only extra stoppage minutes with another subcode | 1,346 |
| Empty | no hours and no stoppage | 223 (removed) |

**Data-quality problems and treatment**

| # | Problem | Volume | Treatment (rule) |
|---|---|---|---|
| DQ1 | Shift missing: never captured in 2022 and mostly missing in 2023 | 3,892 rows | Member `No registrado` (SK −1) (R06) |
| DQ2 | Redundant column: `Unidad por display` holds the shift again (incl. variant `10pm-6am`) | 676 rows | Used as fallback, aliases unified, column dropped (R05) |
| DQ3 | Two coding schemes in `Tipo de paro` (old `17. PARO DE MAQUINA` vs new `[18] Paro de maquina por ventas`) | 1,460 rows in old scheme | Mapping to 12 unified shift statuses (R07) |
| DQ4 | Inconsistent subcode text (`1.2D  RETENEDORES Y ORING ` vs `1.2.C Cambio de Valvula`) | 3,691 stoppages with subcode | Regex to the `N.N[.X]` key + join to catalog; 100% recognized (R12) |
| DQ15 | **Renumbered subcodes**: operational adjustments were code 4 in the old scheme, so their subcodes were typed `4.x` | 940 stoppages | Renumbered `4.x → 5.x` by subsystem name (R12) |
| DQ5 | Mixed record types in one table | see table above | Classified; complements linked to their parent form (R11, R14) |
| DQ6 | Outliers: up to 9,417 bales in one shift (Vinilos_1, Jul-2023) | 15 rows / 53,248 bales | `es_atipico`: excluded **only from Performance**, kept in totals (R17) |
| DQ7 | Reference typos (`Alocdor`, `Stilo Kids`, `(12col)`, `30 cc`) | 505 rows; 52 → 49 values | Normalization function (R08) |
| DQ8 | Exact duplicates | 42 rows | Removed, first occurrence kept (R03) |
| DQ9 | Stoppage longer than the hours worked | 48 forms | Flag `paro_excede_turno`, derived hours floored at 0 (R15) |
| DQ10 | Columns 100% empty (`Unidades producidas cada minuto`, `Display por paca`) | 2 columns | Dropped; values come from the catalog (R04) |
| DQ11 | Placeholder or missing operator (`No`, `No aplica`, empty) | 532 + 3,704 | SK 0 `No aplica` / SK −1 `No registrado` (R10) |
| DQ12 | No reference in 2022 and most of 2023 | 3,855 rows | SK −1; Performance not computable → 2,308 production forms out of P (R09, R16) |
| DQ13 | Procedure vs Excel: PDF lists 17 codes, Excel has 18 (`[18]` Ventas / Desinfección) | — | Code 18 added to the catalog, classified as planned |
| DQ14 | Personal data: operator and maintenance staff names | 47 people | Pseudonymized before staging (R01) |

**Good news for reconciliation.** The 18 hour columns add up exactly to `Tiempo de Paro` (8,449.65 h) and minutes ÷ 60 = hours in every row.

**Limits of the current scheme.** Manual retyping from paper; 18 wide columns make Pareto and drill-down impossible without pivot tables; two coding schemes; no record of rejected units; no OEE definition; no near-real-time visibility.

---

## 3. KPI catalog

### 3.1 OEE time model

```
Shift time (Horas trabajadas)
 ├─ Planned stoppages: 08 training/meeting, 15 supplies change, 16 meals & cleaning, 17 active break, 18 sales/disinfection
 └─ Planned Production Time (PPT)
     ├─ Availability losses: 01–07, 09, 10, 13, 14 (unplanned stoppages)
     └─ Run time
         ├─ Quality losses: 11 rework, 12 defective raw material   ← Q proxy
         └─ Speed losses: real bales vs ideal bales                ← P
```

Non-scheduled shifts (`Horas no programadas`) are **outside OEE**; they feed TEEP / utilization.

### 3.2 Indicators

| KPI | Formula | Unit | Grain | Target / threshold | Source | User |
|---|---|---|---|---|---|---|
| **Production** *(P-MTO-22)* | Σ bales | bales | machine × month × year | — | fact_produccion_turno | Management |
| **% stoppage by code** *(P-MTO-22)* | stoppage h of code ÷ hours worked | % | machine × code × month | — | fact_paro | Management, maintenance |
| **Detail of codes 01/03/05** *(P-MTO-22)* | stoppage h by subcode | h | machine × subcode × month | — | fact_paro | Maintenance |
| **Availability (A)** | run time ÷ PPT | % | any level (ratio of sums) | ≥ 85% | fact_produccion_turno | All |
| **Performance (P)** | Σ bales ÷ Σ ideal bales; ideal = run time × units/min × 60 ÷ units per bale | % | from 2023 | ≥ 90% | fact_produccion_turno + catalog | All |
| **Quality (Q, proxy)** | 1 − hours of codes 11+12 ÷ run time | % | any level | ≥ 99% | fact_produccion_turno | Quality |
| **OEE** | A × P × Q | % | any level | target ≥ 75%; alert < 60% | derived | All |
| **TEEP** *(new)* | OEE × PPT ÷ (PPT + non-scheduled hours) | % | machine × month | informative | derived | Planning |
| **MTBF** *(new)* | run time ÷ # failures (code 01 events) | h | machine × month/year | ↑ | both facts | Maintenance |
| **MTTR** *(new)* | code-01 hours ÷ # failures | h | machine × month/year | ≤ 0.5 h | fact_paro | Maintenance |
| **Bales per hour worked** *(new)* | Σ bales ÷ Σ hours worked | bales/h | machine × reference × shift | vs ideal | fact_produccion_turno | Supervisor |
| **% unplanned stoppage** *(new)* | availability-class hours ÷ total stoppage hours | % | machine × month | ↓ | fact_paro | Management |
| **Pareto concentration** *(new)* | # codes that reach 80% of stoppage hours | # | period | — | fact_paro | Management |

**Why the new KPIs.** The Excel reports volumes and percentages but never combines them. OEE turns everything into one comparable number. MTBF/MTTR separate "fails often" from "takes long to repair", which lead to different decisions (preventive plan vs spare-parts stock/training). TEEP shows capacity lost to commercial reasons, not plant reasons.

**Quality (decision 1).** The source does not record rejected units, so Q is approximated with the time lost to rework [11] and defective raw material [12]. The assumption is visible in the report and in a tooltip of the DAX measure.

### 3.3 Baseline (SQL query Q1)

| Machine | OEE 2023 | OEE 2024 | OEE 2025 (Q1) | Reading |
|---|---|---|---|---|
| Vinilos_1 | 64.3% | 54.1% | 75.5% | worst 2024; strong recovery in 2025 |
| Vinilos_2 | 65.3% | 59.7% | 55.7% | **only line falling every year — availability drops from 78% to 66%** |
| Vinilos_3 | 86.4% | 81.2% | 75.9% | Performance ≈ 100% → the catalog speed (80 upm) is probably understated (see SCD2) |
| Vinilos_4 | 82.2% | 78.5% | 79.7% | most stable line |

Pareto 2022–2025: [16] meals & cleaning 23.7% (planned), **[05] operational adjustment 21.5%**, **[06] spill cleaning 18.3%**, [17] active break 8.5%, [07] changeover 7.4%. Electromechanical failures [01] are only 3.8%. Inside [05], the **dosing system (5.2)** alone accounts for 784 h.

---

## 4. Dimensional model

### 4.1 Approach: Kimball star schemas (fact constellation)

- Analytical queries (aggregations by machine/period/cause) run best on stars with few joins, both in Power BI (VertiPaq) and in Grafana SQL.
- The three business processes share **conformed dimensions** (date, shift, machine, reference, person), so a constellation crosses them without duplicating dimensions.
- Discarded: **Inmon/3NF** (overkill for one source and one department) and a **full snowflake** (extra joins Power BI collapses anyway). The stoppage hierarchy is flattened (§5).

### 4.2 Fact tables and grain

| Fact | Type | Grain (one row = …) | Measures |
|---|---|---|---|
| `fact_produccion_turno` | Transactional | **one shift form**: machine × date × shift × operator × reference, or one non-scheduled shift declaration | hours worked, non-scheduled hours, planned / availability / quality stoppage hours (incl. its complement records), PPT, run time, bales, ideal bales, flags |
| `fact_paro` | Transactional (unpivot) | **one stoppage cause in one source record**: record × code × subcode | minutes, hours, failure event |
| `fact_produccion_hora` | Transactional (near real time) | **one machine-hour**: machine × simulated hour | planned/unplanned/run minutes, bales, ideal, target, A, P, Q, OEE |

`registro_id` (Excel row) is a **degenerate dimension**; `fact_paro.registro_padre_id` links each stoppage to its shift form.

### 4.3 Dimensions

| Dimension | Main attributes | Hierarchy | Notes |
|---|---|---|---|
| `dim_fecha` | date, ISO weekday, week, month, quarter, year, `es_festivo`, `nombre_festivo`, `es_dia_habil` | Año → Trimestre → Mes → Día | **Built by us**: `generate_series` + Colombian holidays computed in PL/pgSQL (Easter + Ley Emiliani) |
| `dim_turno` | shift, start/end, duration, scheme (3x8 / 2x12 / 1x10.5), night flag | Esquema → Turno | −1 / 0 special members |
| `dim_maquina` | machine, line, plant, `velocidad_ideal_upm`, validity dates, `es_actual` | Planta → Línea → Máquina | **SCD Type 2** |
| `dim_referencia` | SKU, brand, presentation (cc), colors, units per bale, in catalog | Marca → Presentación → Referencia | brand/size parsed from the name |
| `dim_persona` | pseudonym, main role | Rol → Persona | **Role-playing**: operator and person involved (code 05) |
| `dim_causa_paro` | area, code, system, component, OEE class | Área → Código → Sistema → Componente | flattened ragged hierarchy |
| `dim_estado_turno` | unified status, category, unified code | Categoría → Estado | absorbs DQ3 |

---

## 5. Stoppage hierarchy

The hierarchy is **ragged**: only codes 01, 03 and 05 have subcodes and only 01 reaches a third level (e.g. `1.2.C Cambio de válvula`). It is modeled as **one flattened dimension of fixed depth** (Área → Código → Sistema → Componente) where the missing levels take `Sin subcódigo` / `Sin detalle`. Each code has a level-1 member, so a stoppage typed without subcode still lands in the right code.

Alternatives discarded: a **parent-child** table needs `PATH()` functions in DAX and no native drill-down; a **snowflake** adds two joins for a 4-level fixed tree; a **bridge** table is unnecessary because each stoppage belongs to exactly one leaf (1:N, not N:M).

---

## 6. Bus matrix

| Business process ↓ / Dimension → | Fecha | Turno | Máquina | Referencia | Persona (operario) | Persona (involucrada) | Causa paro | Estado turno |
|---|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| Shift production (`fact_produccion_turno`) | ✔ | ✔ | ✔ | ✔ | ✔ | | | ✔ |
| Stoppages (`fact_paro`) | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ | |
| Hourly monitoring (`fact_produccion_hora`) | ✔ | ✔ | ✔ | ✔ | | | ✔ (main cause) | |

### Bonus: SCD

- **`dim_maquina` → Type 2** on `velocidad_ideal_upm`. Performance depends on the ideal speed; if a speed change overwrote the row (Type 1), the whole history would be recalculated with the new speed. With Type 2 each fact keeps the version in force on its date (lookup by `vigente_desde ≤ fecha < vigente_hasta`). The data suggest it is needed: Vinilos_3 runs at ≈ 100% Performance, a sign that its catalog speed is outdated. Demo: `sql/demo/01_scd2_cambio_velocidad.sql` (80 → 95 upm).
- **`dim_persona` → Type 1** (pseudonym/role corrections, no history needed).
- **`dim_referencia` → Type 1** for name fixes; Type 2 would apply if units per bale changed.

---

## 7. Personal data

Ley 1581 de 2012 (habeas data). The ETL replaces each name with `PER-xxxxxx` (salted SHA-256, salt in `.env`) **before** writing staging, so real names never reach the database. Power BI reads with `powerbi_ro` (only `dw`), Grafana with `grafana_ro`; the Excel is git-ignored.

---

## 8. Decisions (closed)

1. **Quality in OEE:** time-based proxy with codes 11 + 12. ✔
2. **Outliers (DQ6):** excluded only from Performance; kept in production totals. ✔
3. **Grafana alert:** hourly OEE < 60% for 2 consecutive hours. ✔
4. **Repo:** `bi-paros-envasado`. ✔
