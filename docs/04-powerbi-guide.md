# 04 — Power BI: Semantic Model and Report (step by step)

Menu labels are written exactly as they appear in Power BI Desktop **in Spanish**.

Prerequisite: `docker compose up -d` is running and the ETL finished (`docker compose logs etl` ends in `ETL OK`).

---

## 1. Connect to PostgreSQL (not to the Excel)

1. **Inicio → Obtener datos → Más… → Base de datos PostgreSQL → Conectar**.
2. Servidor: `localhost:<DB_PORT>` (5432 by default; 5433 on the development PC because 5432 was taken) · Base de datos: `bi_paros` · Modo de conectividad: **Importar** → Aceptar.
3. Credentials: tab **Base de datos**, user `powerbi_ro`, password = `POWERBI_DB_PASSWORD` from `.env`.
   If an SSL/certificate error appears: **Archivo → Opciones y configuración → Configuración de origen de datos → localhost;bi_paros → Editar permisos → uncheck "Cifrar conexiones"**.
4. In the Navigator select (schema `dw`):
   `dim_fecha, dim_turno, dim_maquina, dim_referencia, dim_persona, dim_causa_paro, dim_estado_turno, fact_produccion_turno, fact_paro` → **Cargar**.
   `fact_produccion_hora` is not needed (it belongs to Grafana).

Why Import: the dataset is small (~23k fact rows), Import gives full DAX time intelligence and fast visuals. The refresh is on demand / monthly, which matches the strategic user.

## 2. Rename tables

In **Vista de modelo**, double-click each table and remove the `dw ` prefix (e.g. `dw fact_paro` → `fact_paro`). The DAX script uses the names without prefix.

## 3. Relationships (Vista de modelo → Administrar relaciones)

Power BI autodetects the ones whose columns have the same name. Check that these exist, all **Varios a uno (*:1)**, cross-filter **Único**:

| From (many) | To (one) | Active |
|---|---|---|
| fact_produccion_turno[fecha_sk] | dim_fecha[fecha_sk] | ✔ |
| fact_produccion_turno[turno_sk] | dim_turno[turno_sk] | ✔ |
| fact_produccion_turno[maquina_sk] | dim_maquina[maquina_sk] | ✔ |
| fact_produccion_turno[referencia_sk] | dim_referencia[referencia_sk] | ✔ |
| fact_produccion_turno[estado_sk] | dim_estado_turno[estado_sk] | ✔ |
| fact_produccion_turno[operario_sk] | dim_persona[persona_sk] | ✔ (create by hand) |
| fact_paro[fecha_sk] | dim_fecha[fecha_sk] | ✔ |
| fact_paro[turno_sk] | dim_turno[turno_sk] | ✔ |
| fact_paro[maquina_sk] | dim_maquina[maquina_sk] | ✔ |
| fact_paro[referencia_sk] | dim_referencia[referencia_sk] | ✔ |
| fact_paro[causa_sk] | dim_causa_paro[causa_sk] | ✔ |
| fact_paro[operario_sk] | dim_persona[persona_sk] | ✔ (create by hand) |
| fact_paro[persona_involucrada_sk] | dim_persona[persona_sk] | ✘ **inactive** (role-playing, used with `USERELATIONSHIP`) |

Do **not** relate `fact_paro[registro_padre_id]` with `fact_produccion_turno`: two facts related to each other would create ambiguous filter paths. Facts only talk through the conformed dimensions.

## 4. Model settings

- `dim_fecha` → **Herramientas de tabla → Marcar como tabla de fechas** → column `fecha`. Required for `SAMEPERIODLASTYEAR`, `TOTALYTD`, `DATEADD`.
- `dim_fecha[nombre_mes]` → **Herramientas de columnas → Ordenar por columna → mes**.
- `dim_causa_paro[codigo_label]` → **Ordenar por columna → codigo**.
- Hierarchies (right click on the first field → **Crear jerarquía**, then **Agregar a la jerarquía**):
  - `dim_causa_paro`: **Jerarquía Paros** = area_impacto → codigo_label → sistema → componente
  - `dim_fecha`: **Calendario** = anio → trimestre → nombre_mes → fecha
  - `dim_maquina`: planta → linea → maquina_nk
- Hide the `_sk` keys in every table (right click → **Ocultar en la vista de informe**).

## 5. Measures

1. **Inicio → Introducir datos** → table name `_Medidas`, leave one empty column → **Cargar**.
2. The measures were created with a `createOrReplace` script in the **Vista TMDL**, with display folders (1. Bases, 2. OEE, 3. Inteligencia de tiempo, 4. Paros, 5. Mantenimiento). The same logic is in `powerbi/medidas.dax` for the **Vista de consultas DAX** (paste → CodeLens **"Actualizar modelo"** → **Ejecutar**).
3. Format: select the % measures (Disponibilidad, Rendimiento, Calidad, OEE, TEEP, OEE Año Anterior, Var…, % …, Pareto % Acumulado, Meta OEE, Umbral Alerta OEE, Línea 80%) → **Herramientas de medición → Formato: Porcentaje**, 1 decimal.
4. Hide the empty column of `_Medidas`; the table turns into a measure folder.

**Validation (all years, by machine)** — the DAX result must match the SQL view:

| Machine | Disponibilidad | Rendimiento | Calidad | OEE | Horas paro | MTTR (h) |
|---|---|---|---|---|---|---|
| Vinilos_1 | 81.8% | 77.0% | 98.8% | 62.3% | 2,044.6 | 0.70 |
| Vinilos_2 | 76.5% | 83.0% | 98.9% | 62.9% | 1,367.2 | 0.72 |
| Vinilos_3 | 87.7% | 96.8% | 99.3% | 84.3% | 2,405.3 | 0.65 |
| Vinilos_4 | 87.6% | 93.1% | 99.4% | 81.1% | 2,614.4 | 0.72 |

## 6. Report pages

The repository already contains the finished project (`powerbi/BI_Paros_Envasado.pbip`). The first version of the pages was generated with `powerbi/build_report_pages.py` (PBIR files, run with Power BI Desktop closed) and then adjusted by hand. To make the visuals readable, these columns were renamed in the model: `anio` → **Año**, `anio_mes` → **Año-Mes**, `maquina_nk` → **Máquina**, `turno_nk` → **Turno**, `area_impacto` → **Área**, `codigo_label` → **Código**, `sistema` → **Sistema**, `componente` → **Componente**, `clase_oee` → **Clase OEE**, `referencia_nk` → **Referencia**, `categoria` → **Categoría**.

Common to every page: slicers **Año**, **Máquina**, **Turno** (dropdown) and a page navigator (**Insertar → Botones → Navegador → Navegador de páginas**, copied to every page).

### Page 1 — Resumen ejecutivo (management, Q1 and Q3)
- 5 **Tarjetas**: OEE, Disponibilidad, Rendimiento, Calidad (approximate), Pacas Producidas.
- **Gráfico de líneas**: X = Año-Mes, Y = OEE, Leyenda = Máquina.
- **Medidor**: OEE with target = Meta OEE (75%).
- **Columnas agrupadas**: X = Año, Y = OEE and OEE Año Anterior.
- **Matriz** "Resumen por máquina": Máquina; OEE, Var OEE vs Año Anterior (pp), TEEP, Horas Paro. The variation only shows when one year is selected (see §5 notes).

### Page 2 — Análisis de paros (Pareto + drill-down, Q2 and Q4)
- **Gráfico de columnas y líneas** (Pareto): X = Código, columns = Horas Paro, lines = Pareto % Acumulado and Línea 80% (secondary axis), sorted by Horas Paro descending.
- **Matriz** with drill-down: Rows = Área → Código → Sistema → Componente; Values = Horas Paro, % Participación Paro, Eventos de Paro. The **+ / −** icons open each level.
- **Árbol de descomposición**: Analizar = Horas Paro; Explicar por = Área, Código, Sistema, Componente, Máquina.
- **Columnas agrupadas**: X = Máquina, Y = % Paro sobre Horas Trabajadas, Leyenda = Clase OEE (P-MTO-22 indicator).

### Page 3 — Mantenimiento (Q4, Q5, Q6)
- **Tarjetas**: Fallas (code 01), MTTR (h), MTBF (h).
- **Columnas y líneas**: X = Máquina, columns = MTBF (h), line = MTTR (h) on the secondary axis (the scales differ by two orders of magnitude).
- **Matriz**: Rows = Sistema → Componente; Values = Fallas, Horas Falla, MTTR (h).
- **Gráfico de líneas**: X = Año-Mes, Y = Horas Paro, Leyenda = Código.

### Page 4 — Producción y planeación (Q10, Q11, Q12, P-MTO-22 production)
- **Matriz**: Rows = Máquina, Columns = Año, Values = Pacas Producidas.
- **Gráfico de anillos**: Horas No Programadas by Categoría.
- **Barras**: Rendimiento by Referencia, ascending (worst references first).
- **Matriz**: Turno; Pacas por Hora, Disponibilidad.

### Notes found while reviewing the report
- `dim_fecha` covers 2022–2027. With no year selected, `SAMEPERIODLASTYEAR` over the whole range overlaps the same facts and returned the same OEE as the current period, so `OEE Año Anterior` and `Pacas Año Anterior` only answer when `HASONEVALUE(dim_fecha[Año])` and the current year has data.
- `Código` is sorted by `codigo`, and Power BI adds the sort column to the visual query. `ALLSELECTED(dim_causa_paro[Código])` alone left the `codigo` filter in place, so the Pareto line showed each cause's own share. The fix clears both columns: `ALLSELECTED(dim_causa_paro[Código], dim_causa_paro[codigo])`.
- 2022 has no OEE on purpose: no reference was recorded that year (DQ12), so there is no ideal rate and Performance cannot be computed. Bales are still counted.

## 7. Save as PBIP (Git-friendly)

**Archivo → Opciones y configuración → Opciones → Características de versión preliminar** → enable **"Almacenamiento de modelo semántico en formato TMDL"** and **"Almacenar informes con formato de metadatos mejorado (PBIR)"** → restart.
**Archivo → Guardar como → Proyecto de Power BI (*.pbip)** → `powerbi/BI_Paros_Envasado.pbip`.

`.gitignore` already excludes `cache.abf` and `localSettings.json`, so no data and no credentials reach the repo.
