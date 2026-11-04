-- =============================================================================
-- 06_views.sql — KPI views (reused by Grafana panels and by the analytical
-- queries). Power BI imports the star tables directly and recomputes the KPIs
-- in DAX; these views are the SQL reference to validate the DAX results.
--
-- OEE time model
--   PPT (horas_planificadas) = horas trabajadas − paros planificados (08,15,16,17,18)
--   Run time (horas_operativas) = PPT − paros de disponibilidad (01–07, 09, 10, 13, 14)
--   A = run time / PPT
--   P = pacas / pacas ideales           (only rows with incluir_en_rendimiento)
--   Q = 1 − horas de calidad (11, 12) / run time      (proxy: no reject count in source)
--   OEE = A × P × Q
-- =============================================================================

CREATE OR REPLACE VIEW dw.vw_kpi_mensual_maquina AS
WITH prod AS (
    SELECT f.anio, f.mes, f.anio_mes, m.maquina_nk,
           SUM(p.horas_trabajadas)                                         AS horas_trabajadas,
           SUM(p.horas_no_programadas)                                     AS horas_no_programadas,
           SUM(p.horas_planificadas)                                       AS horas_planificadas,
           SUM(p.horas_operativas)                                         AS horas_operativas,
           SUM(p.horas_paro_calidad)                                       AS horas_calidad,
           SUM(p.horas_paro_total)                                         AS horas_paro,
           SUM(p.pacas_producidas)                                         AS pacas,
           SUM(p.pacas_producidas) FILTER (WHERE p.incluir_en_rendimiento) AS pacas_rend,
           SUM(p.pacas_ideales)    FILTER (WHERE p.incluir_en_rendimiento) AS pacas_ideales
    FROM dw.fact_produccion_turno p
    JOIN dw.dim_fecha   f ON f.fecha_sk   = p.fecha_sk
    JOIN dw.dim_maquina m ON m.maquina_sk = p.maquina_sk
    GROUP BY f.anio, f.mes, f.anio_mes, m.maquina_nk
), fallas AS (
    SELECT f.anio_mes, m.maquina_nk,
           COUNT(*) FILTER (WHERE fp.evento_falla = 1)                 AS n_fallas,
           SUM(fp.horas_paro) FILTER (WHERE fp.evento_falla = 1)       AS horas_falla
    FROM dw.fact_paro fp
    JOIN dw.dim_fecha   f ON f.fecha_sk   = fp.fecha_sk
    JOIN dw.dim_maquina m ON m.maquina_sk = fp.maquina_sk
    GROUP BY f.anio_mes, m.maquina_nk
)
SELECT p.anio, p.mes, p.anio_mes, p.maquina_nk,
       p.horas_trabajadas, p.horas_no_programadas, p.horas_paro, p.pacas,
       ROUND(p.horas_operativas / NULLIF(p.horas_planificadas, 0), 4)                 AS disponibilidad,
       ROUND(p.pacas_rend / NULLIF(p.pacas_ideales, 0), 4)                            AS rendimiento,
       ROUND(1 - p.horas_calidad / NULLIF(p.horas_operativas, 0), 4)                  AS calidad,
       ROUND( (p.horas_operativas / NULLIF(p.horas_planificadas, 0))
            * (p.pacas_rend / NULLIF(p.pacas_ideales, 0))
            * (1 - p.horas_calidad / NULLIF(p.horas_operativas, 0)), 4)               AS oee,
       COALESCE(fa.n_fallas, 0)                                                       AS n_fallas,
       ROUND(p.horas_operativas / NULLIF(fa.n_fallas, 0), 2)                          AS mtbf_h,
       ROUND(fa.horas_falla / NULLIF(fa.n_fallas, 0), 2)                              AS mttr_h
FROM prod p
LEFT JOIN fallas fa ON fa.anio_mes = p.anio_mes AND fa.maquina_nk = p.maquina_nk;

COMMENT ON VIEW dw.vw_kpi_mensual_maquina IS 'A, P, Q, OEE, MTBF and MTTR per machine and month';

-- Pareto of stoppage causes (code level) with cumulative share
CREATE OR REPLACE VIEW dw.vw_pareto_causas AS
SELECT c.codigo_label, c.area_impacto, c.clase_oee,
       ROUND(SUM(fp.horas_paro), 2)                                              AS horas_paro,
       ROUND(100.0 * SUM(fp.horas_paro) / SUM(SUM(fp.horas_paro)) OVER (), 2)    AS pct,
       ROUND(100.0 * SUM(SUM(fp.horas_paro)) OVER (ORDER BY SUM(fp.horas_paro) DESC
                                                   ROWS UNBOUNDED PRECEDING)
             / SUM(SUM(fp.horas_paro)) OVER (), 2)                               AS pct_acumulado
FROM dw.fact_paro fp
JOIN dw.dim_causa_paro c ON c.causa_sk = fp.causa_sk
GROUP BY c.codigo_label, c.area_impacto, c.clase_oee;

-- Latest simulated hour per machine (Grafana "estado actual")
CREATE OR REPLACE VIEW dw.vw_rt_estado_actual AS
SELECT DISTINCT ON (h.maquina_sk)
       m.maquina_nk, h.ts, h.hora_simulada, t.turno_nk, r.referencia_nk,
       h.modo_simulacion, h.pacas, h.pacas_meta,
       h.disponibilidad, h.rendimiento, h.calidad, h.oee,
       h.minutos_paro_no_planif, c.codigo_label AS causa_principal,
       CASE WHEN h.minutos_operativos = 0 THEN 'PARADA'
            WHEN h.oee < 0.60            THEN 'CRÍTICO'
            WHEN h.oee < 0.75            THEN 'BAJO META'
            ELSE 'OK' END                                                AS estado
FROM dw.fact_produccion_hora h
JOIN dw.dim_maquina    m ON m.maquina_sk    = h.maquina_sk
JOIN dw.dim_turno      t ON t.turno_sk      = h.turno_sk
JOIN dw.dim_referencia r ON r.referencia_sk = h.referencia_sk
LEFT JOIN dw.dim_causa_paro c ON c.causa_sk = h.causa_principal_sk
ORDER BY h.maquina_sk, h.ts DESC;
