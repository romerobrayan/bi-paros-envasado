-- =============================================================================
-- 02_reconciliation.sql — Prove that loaded totals match the source
-- The ETL stores the comparison in etl.reconciliacion; these queries let you
-- re-check it live in DBeaver against the raw staging copy.
-- =============================================================================

-- 1. Result stored by the last successful ETL run
SELECT r.metrica, r.valor_fuente, r.valor_cargado, r.diferencia, r.explicacion
FROM etl.reconciliacion r
WHERE r.run_id = (SELECT MAX(run_id) FROM etl.run_log WHERE status = 'OK')
ORDER BY r.metrica;

-- 2. Cleaning rules with counts before / affected / after
SELECT rule_id, dq_ref, regla, filas_antes, filas_afectadas, filas_despues, accion
FROM etl.dq_log
WHERE run_id = (SELECT MAX(run_id) FROM etl.run_log WHERE status = 'OK')
ORDER BY rule_id;

-- 3. Independent check: raw staging (all 8,208 rows) vs warehouse
WITH src AS (
    SELECT SUM(NULLIF(horas_trabajadas, '')::numeric)  AS horas,
           SUM(NULLIF(pacas_producidas, '')::numeric)  AS pacas,
           SUM(NULLIF(tiempo_de_paro, '')::numeric)    AS paro
    FROM stg.base_datos_raw
), dw_ AS (
    SELECT (SELECT SUM(horas_trabajadas) FROM dw.fact_produccion_turno) AS horas,
           (SELECT SUM(pacas_producidas) FROM dw.fact_produccion_turno) AS pacas,
           (SELECT SUM(horas_paro)       FROM dw.fact_paro)             AS paro
)
SELECT 'Horas trabajadas' AS metrica, ROUND(src.horas, 2) AS fuente, ROUND(dw_.horas, 2) AS dw,
       ROUND(dw_.horas - src.horas, 2) AS diferencia FROM src, dw_
UNION ALL
SELECT 'Pacas producidas', ROUND(src.pacas, 2), ROUND(dw_.pacas, 2), ROUND(dw_.pacas - src.pacas, 2) FROM src, dw_
UNION ALL
SELECT 'Tiempo de paro (h)', ROUND(src.paro, 2), ROUND(dw_.paro, 2), ROUND(dw_.paro - src.paro, 2) FROM src, dw_;

-- 4. The difference is exactly the removed duplicates: rows in staging not loaded in any fact
SELECT COUNT(*) AS filas_no_cargadas,
       ROUND(SUM(NULLIF(s.horas_trabajadas, '')::numeric), 2) AS horas,
       ROUND(SUM(NULLIF(s.pacas_producidas, '')::numeric), 2) AS pacas,
       ROUND(SUM(NULLIF(s.tiempo_de_paro, '')::numeric), 2)   AS paro
FROM stg.base_datos_raw s
WHERE NOT EXISTS (SELECT 1 FROM dw.fact_produccion_turno p WHERE p.registro_id = s.source_row)
  AND NOT EXISTS (SELECT 1 FROM dw.fact_paro fp WHERE fp.registro_id = s.source_row);

-- 5. Per machine and year: stoppage hours in the source vs the warehouse
SELECT s.maquina, EXTRACT(YEAR FROM s.fecha::timestamp)::int AS anio,
       ROUND(SUM(NULLIF(s.tiempo_de_paro, '')::numeric), 2) AS paro_fuente,
       ROUND(d.paro_dw, 2) AS paro_dw
FROM stg.base_datos_raw s
JOIN LATERAL (
    SELECT SUM(fp.horas_paro) AS paro_dw
    FROM dw.fact_paro fp
    JOIN dw.dim_maquina m ON m.maquina_sk = fp.maquina_sk
    JOIN dw.dim_fecha f   ON f.fecha_sk = fp.fecha_sk
    WHERE m.maquina_nk = s.maquina AND f.anio = EXTRACT(YEAR FROM s.fecha::timestamp)
) d ON true
GROUP BY s.maquina, EXTRACT(YEAR FROM s.fecha::timestamp), d.paro_dw
ORDER BY 1, 2;
