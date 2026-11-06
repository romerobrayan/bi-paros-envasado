# 04 — Power BI: Semantic Model and Report (step by step)

Menu labels are written exactly as they appear in Power BI Desktop **in Spanish**.

Prerequisite: `docker compose up -d` is running and the ETL finished (`docker compose logs etl` ends in `ETL OK`).

---

## 1. Connect to PostgreSQL (not to the Excel)

1. **Inicio → Obtener datos → Más… → Base de datos PostgreSQL → Conectar**.
2. Servidor: `localhost:5432` · Base de datos: `bi_paros` · Modo de conectividad: **Importar** → Aceptar.
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
2. **Vista de consultas DAX** → paste `powerbi/medidas.dax` → click the CodeLens **"Actualizar modelo: agregar … medidas nuevas"** → **Ejecutar**.
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

Common to every page: slicers **Año** (dim_fecha[anio]), **Máquina** (dim_maquina[maquina_nk]), **Turno** (dim_turno[turno_nk]); a title; and the page navigator (**Insertar → Botones → Navegador → Navegador de páginas**). To sync slicers across pages: **Ver → Sincronizar segmentaciones**.

### Page 1 — Resumen ejecutivo (management, Q1 and Q3)
- 5 **Tarjetas**: OEE, Disponibilidad, Rendimiento, Calidad, Pacas Producidas.
- **Medidor** (gauge): OEE with target = Meta OEE.
- **Gráfico de líneas**: X = Calendario (anio → nombre_mes), Y = OEE, Leyenda = maquina_nk; add Meta OEE as a second line.
- **Gráfico de columnas agrupadas**: X = maquina_nk, Y = OEE and OEE Año Anterior (YoY comparison).
- **Tabla**: maquina_nk, OEE, Var OEE vs Año Anterior (pp), TEEP, with conditional format (red < 60%, amber < 75%, green ≥ 75%).

### Page 2 — Análisis de paros (Pareto + drill-down, Q2 and Q4)
- **Gráfico de columnas y líneas** (Pareto): X = codigo_label, Columns = Horas Paro, Line = Pareto % Acumulado, Line = Línea 80% (secondary axis 0–100%). Sort by Horas Paro descending.
- **Matriz** with drill-down: Rows = Jerarquía Paros (Área → Código → Sistema → Componente), Values = Horas Paro, % Participación Paro, Eventos de Paro. Use the **+** icons / "Expandir un nivel" to show the drill.
- **Árbol de descomposición**: Analizar = Horas Paro, Explicar por = area_impacto, codigo_label, sistema, componente, maquina_nk.
- **Gráfico de barras apiladas**: X = maquina_nk, Y = % Paro sobre Horas Trabajadas, Leyenda = clase_oee (P-MTO-22 indicator).

### Page 3 — Mantenimiento (Q4, Q5, Q6)
- **Tarjetas**: Fallas, MTTR (h), MTBF (h).
- **Gráfico de columnas**: X = maquina_nk, Y = MTBF (h) and MTTR (h).
- **Matriz**: Rows = sistema → componente filtered with **Filtros en este objeto visual** codigo = 1, Values = Fallas, Horas Falla, MTTR (h).
- **Gráfico de líneas**: X = Calendario, Y = Horas Paro and Horas Paro Mes Anterior, filter codigo in {3, 5} (power supply and operational adjustments).

### Page 4 — Producción y planeación (Q10, Q11, P-MTO-22 production)
- **Matriz**: Rows = maquina_nk, Columns = anio → nombre_mes, Values = Pacas Producidas (the P-MTO-22 "production by machine, month and year").
- **Gráfico de columnas agrupadas**: X = nombre_mes, Y = Pacas Producidas and Pacas Año Anterior.
- **Gráfico de barras**: Y = referencia_nk (Top N 10 by Rendimiento ascending), X = Rendimiento.
- **Gráfico de anillos**: Horas No Programadas by dim_estado_turno[categoria].
- **Tabla**: turno_nk, esquema, Pacas por Hora, Disponibilidad.

## 7. Save as PBIP (Git-friendly)

**Archivo → Opciones y configuración → Opciones → Características de versión preliminar** → enable **"Almacenamiento de modelo semántico en formato TMDL"** and **"Almacenar informes con formato de metadatos mejorado (PBIR)"** → restart.
**Archivo → Guardar como → Proyecto de Power BI (*.pbip)** → `powerbi/BI_Paros_Envasado.pbip`.

`.gitignore` already excludes `cache.abf` and `localSettings.json`, so no data and no credentials reach the repo.
