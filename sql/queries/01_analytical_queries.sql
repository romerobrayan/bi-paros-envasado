-- =============================================================================
-- 01_analytical_queries.sql — Business questions answered with SQL
-- Run in DBeaver connected to the bi_paros database.
-- Techniques: aggregations, window functions (RANK, LAG, running SUM, NTILE,
-- moving AVG, PERCENTILE), period-over-period comparisons, FILTER, ROLLUP.
-- =============================================================================

-- Q1. OEE per machine and year, with year-over-year change (LAG)
WITH anual AS (
    SELECT m.maquina_nk, f.anio,
           SUM(p.horas_operativas) / NULLIF(SUM(p.horas_planificadas), 0)                       AS a,
           SUM(p.pacas_producidas) FILTER (WHERE p.incluir_en_rendimiento)
             / NULLIF(SUM(p.pacas_ideales) FILTER (WHERE p.incluir_en_rendimiento), 0)          AS p,
           1 - SUM(p.horas_paro_calidad) / NULLIF(SUM(p.horas_operativas), 0)                   AS q
    FROM dw.fact_produccion_turno p
    JOIN dw.dim_fecha f   ON f.fecha_sk = p.fecha_sk
    JOIN dw.dim_maquina m ON m.maquina_sk = p.maquina_sk
    WHERE f.anio >= 2023                       -- Performance is only computable from 2023 (DQ12)
    GROUP BY m.maquina_nk, f.anio
)
SELECT maquina_nk, anio,
       ROUND(100 * a, 1)               AS disponibilidad_pct,
       ROUND(100 * p, 1)               AS rendimiento_pct,
       ROUND(100 * q, 2)               AS calidad_pct,
       ROUND(100 * a * p * q, 1)       AS oee_pct,
       ROUND(100 * (a * p * q - LAG(a * p * q) OVER (PARTITION BY maquina_nk ORDER BY anio)), 1) AS var_oee_pp
FROM anual
ORDER BY maquina_nk, anio;

-- Q2. Pareto of stoppage causes for 2024 (running cumulative share) + ABC class
WITH c AS (
    SELECT dc.codigo_label, dc.clase_oee, SUM(fp.horas_paro) AS horas
    FROM dw.fact_paro fp
    JOIN dw.dim_causa_paro dc ON dc.causa_sk = fp.causa_sk
    JOIN dw.dim_fecha f       ON f.fecha_sk = fp.fecha_sk
    WHERE f.anio = 2024
    GROUP BY dc.codigo_label, dc.clase_oee
)
SELECT RANK() OVER (ORDER BY horas DESC)                                       AS ranking,
       codigo_label, clase_oee,
       ROUND(horas, 1)                                                         AS horas,
       ROUND(100 * horas / SUM(horas) OVER (), 1)                              AS pct,
       ROUND(100 * SUM(horas) OVER (ORDER BY horas DESC ROWS UNBOUNDED PRECEDING)
             / SUM(horas) OVER (), 1)                                          AS pct_acumulado,
       CASE WHEN SUM(horas) OVER (ORDER BY horas DESC ROWS UNBOUNDED PRECEDING) - horas
                 < 0.8 * SUM(horas) OVER () THEN 'A (80%)' ELSE 'B/C' END       AS clase_abc
FROM c
ORDER BY horas DESC;

-- Q4. Which system / component of the machine fails most? (drill code 01 -> system -> component)
SELECT dc.sistema, dc.componente,
       COUNT(*)                                  AS eventos,
       ROUND(SUM(fp.horas_paro), 1)              AS horas,
       ROUND(AVG(fp.minutos_paro), 1)            AS min_promedio_evento,
       GROUPING(dc.componente)                   AS es_subtotal
FROM dw.fact_paro fp
JOIN dw.dim_causa_paro dc ON dc.causa_sk = fp.causa_sk
WHERE dc.codigo = 1
GROUP BY ROLLUP (dc.sistema, dc.componente)
ORDER BY dc.sistema NULLS LAST, es_subtotal DESC, horas DESC;

-- Q5. MTBF and MTTR per machine and year
SELECT m.maquina_nk, f.anio,
       COUNT(*) FILTER (WHERE fp.evento_falla = 1)                                  AS fallas,
       ROUND(op.horas_operativas / NULLIF(COUNT(*) FILTER (WHERE fp.evento_falla = 1), 0), 1) AS mtbf_h,
       ROUND(SUM(fp.horas_paro) FILTER (WHERE fp.evento_falla = 1)
             / NULLIF(COUNT(*) FILTER (WHERE fp.evento_falla = 1), 0), 2)         AS mttr_h
FROM dw.fact_paro fp
JOIN dw.dim_fecha f   ON f.fecha_sk = fp.fecha_sk
JOIN dw.dim_maquina m ON m.maquina_sk = fp.maquina_sk
JOIN LATERAL (SELECT SUM(p.horas_operativas) AS horas_operativas
              FROM dw.fact_produccion_turno p JOIN dw.dim_fecha f2 ON f2.fecha_sk = p.fecha_sk
              WHERE p.maquina_sk = fp.maquina_sk AND f2.anio = f.anio) op ON true
GROUP BY m.maquina_nk, f.anio, op.horas_operativas
ORDER BY m.maquina_nk, f.anio;

-- Q6. Month-over-month and same-month-last-year comparison of stoppage hours (codes 01, 03, 05)
WITH mensual AS (
    SELECT f.anio, f.mes, f.anio_mes, dc.codigo_label, SUM(fp.horas_paro) AS horas
    FROM dw.fact_paro fp
    JOIN dw.dim_fecha f       ON f.fecha_sk = fp.fecha_sk
    JOIN dw.dim_causa_paro dc ON dc.causa_sk = fp.causa_sk
    WHERE dc.codigo IN (1, 3, 5)
    GROUP BY f.anio, f.mes, f.anio_mes, dc.codigo_label
)
SELECT anio_mes, codigo_label, ROUND(horas, 1) AS horas,
       ROUND(horas - LAG(horas) OVER w_mes, 1)                                   AS var_vs_mes_anterior,
       ROUND(horas - LAG(horas, 12) OVER w_mes, 1)                               AS var_vs_mismo_mes_anio_anterior,
       ROUND(AVG(horas) OVER (w_mes ROWS BETWEEN 2 PRECEDING AND CURRENT ROW), 1) AS media_movil_3m
FROM mensual
WINDOW w_mes AS (PARTITION BY codigo_label ORDER BY anio, mes)
ORDER BY codigo_label, anio_mes;
-- note: LAG(…, 12) assumes consecutive months; months without stoppages are absent

-- Q10. Capacity lost to non-scheduled shifts (commercial vs plant reasons)
SELECT f.anio, e.categoria, e.estado_nk,
       COUNT(*)                                 AS turnos,
       ROUND(SUM(p.horas_no_programadas), 0)    AS horas_no_programadas,
       ROUND(100 * SUM(p.horas_no_programadas)
             / SUM(SUM(p.horas_no_programadas)) OVER (PARTITION BY f.anio), 1) AS pct_del_anio
FROM dw.fact_produccion_turno p
JOIN dw.dim_fecha f        ON f.fecha_sk = p.fecha_sk
JOIN dw.dim_estado_turno e ON e.estado_sk = p.estado_sk
WHERE p.tipo_registro = 'NO_PROGRAMADO'
GROUP BY f.anio, e.categoria, e.estado_nk
ORDER BY f.anio, horas_no_programadas DESC;

-- Q11. Worst references by Performance (only rows valid for Performance), quartiles with NTILE
WITH r AS (
    SELECT dr.marca, dr.referencia_nk, COUNT(*) AS turnos,
           SUM(p.pacas_producidas) / NULLIF(SUM(p.pacas_ideales), 0) AS rendimiento
    FROM dw.fact_produccion_turno p
    JOIN dw.dim_referencia dr ON dr.referencia_sk = p.referencia_sk
    WHERE p.incluir_en_rendimiento
    GROUP BY dr.marca, dr.referencia_nk
    HAVING COUNT(*) >= 20
)
SELECT marca, referencia_nk, turnos, ROUND(100 * rendimiento, 1) AS rendimiento_pct,
       NTILE(4) OVER (ORDER BY rendimiento) AS cuartil      -- 1 = worst quarter
FROM r
ORDER BY rendimiento;

-- Q12. Performance by shift scheme (3x8 vs 2x12 vs 10.5 h) and night vs day
SELECT t.esquema, t.turno_nk, t.es_nocturno,
       COUNT(*)                                                               AS turnos,
       ROUND(SUM(p.pacas_producidas) / NULLIF(SUM(p.horas_trabajadas), 0), 2) AS pacas_por_hora,
       ROUND(100 * SUM(p.horas_operativas) / NULLIF(SUM(p.horas_planificadas), 0), 1) AS disponibilidad_pct
FROM dw.fact_produccion_turno p
JOIN dw.dim_turno t ON t.turno_sk = p.turno_sk
WHERE p.tipo_registro = 'PRODUCCION' AND t.turno_sk > 0
GROUP BY t.esquema, t.turno_nk, t.es_nocturno
ORDER BY t.esquema, t.turno_nk;

-- Q13. Day-of-week and holiday effect (uses the calendar dimension built by us)
SELECT f.nombre_dia, f.es_festivo,
       COUNT(*) AS turnos,
       ROUND(AVG(p.horas_paro_disponibilidad), 2) AS paro_no_planif_promedio_h
FROM dw.fact_produccion_turno p
JOIN dw.dim_fecha f ON f.fecha_sk = p.fecha_sk
WHERE p.tipo_registro = 'PRODUCCION'
GROUP BY f.dia_semana, f.nombre_dia, f.es_festivo
ORDER BY f.dia_semana, f.es_festivo;
