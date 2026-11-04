-- =============================================================================
-- 05_indexes.sql — Indexes justified by the analytical query patterns
-- PostgreSQL does NOT index foreign keys automatically. Every index below
-- serves one of the filters that Power BI (DirectQuery/refresh), Grafana and
-- the analytical SQL queries actually use.
-- =============================================================================

-- fact_produccion_turno -------------------------------------------------------
-- "OEE of machine X between dates": filter by machine, range on date
CREATE INDEX IF NOT EXISTS ix_fpt_maquina_fecha ON dw.fact_produccion_turno (maquina_sk, fecha_sk);
-- monthly / yearly trends across all machines: range scans on date
CREATE INDEX IF NOT EXISTS ix_fpt_fecha        ON dw.fact_produccion_turno (fecha_sk);
-- performance by SKU and by shift (Q11)
CREATE INDEX IF NOT EXISTS ix_fpt_referencia   ON dw.fact_produccion_turno (referencia_sk);
CREATE INDEX IF NOT EXISTS ix_fpt_turno        ON dw.fact_produccion_turno (turno_sk);

-- fact_paro -------------------------------------------------------------------
-- Pareto of causes in a period (Q2, Q4): group by cause, filter by date
CREATE INDEX IF NOT EXISTS ix_fp_causa_fecha   ON dw.fact_paro (causa_sk, fecha_sk);
-- stoppages of one machine over time (drill from a machine)
CREATE INDEX IF NOT EXISTS ix_fp_maquina_fecha ON dw.fact_paro (maquina_sk, fecha_sk);
-- join back to the parent shift form
CREATE INDEX IF NOT EXISTS ix_fp_padre         ON dw.fact_paro (registro_padre_id);
-- MTBF / MTTR only read failure events (code 01): a PARTIAL index stays tiny
CREATE INDEX IF NOT EXISTS ix_fp_fallas        ON dw.fact_paro (maquina_sk, fecha_sk) WHERE evento_falla = 1;

-- fact_produccion_hora (append-only time series) ------------------------------
-- BRIN: rows arrive in ts order, so a block-range index is ~1000x smaller than
-- a B-tree and is ideal for Grafana's "$__timeFilter(ts)" range predicates
CREATE INDEX IF NOT EXISTS brin_fph_ts          ON dw.fact_produccion_hora USING brin (ts);
-- "current state per machine" = latest row per machine (DISTINCT ON ... ORDER BY ts DESC)
CREATE INDEX IF NOT EXISTS ix_fph_maquina_ts    ON dw.fact_produccion_hora (maquina_sk, ts DESC);

-- dimensions: lookup by natural key while loading (SCD2 lookup by date range)
CREATE INDEX IF NOT EXISTS ix_maquina_nk_vigencia ON dw.dim_maquina (maquina_nk, vigente_desde, vigente_hasta);
