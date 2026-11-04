-- =============================================================================
-- 01_schemas.sql — Schemas of the solution
--   stg : raw copy of the Excel source (text columns, one row per source row)
--   dw  : dimensional model (star schemas / fact constellation)
--   etl : run log, data-quality log and reconciliation results
--   sim : control tables for the near-real-time simulator (Grafana demo)
--   ops : operational tables written by services (alert sink)
-- =============================================================================
CREATE SCHEMA IF NOT EXISTS stg;
CREATE SCHEMA IF NOT EXISTS dw;
CREATE SCHEMA IF NOT EXISTS etl;
CREATE SCHEMA IF NOT EXISTS sim;
CREATE SCHEMA IF NOT EXISTS ops;

COMMENT ON SCHEMA stg IS 'Staging: raw Excel data loaded as text, with source row number for lineage';
COMMENT ON SCHEMA dw  IS 'Data warehouse: dimensional model consumed by Power BI and Grafana';
COMMENT ON SCHEMA etl IS 'ETL metadata: runs, data-quality rules and reconciliation';
COMMENT ON SCHEMA sim IS 'Hour-by-hour simulator control (near real time demo)';
COMMENT ON SCHEMA ops IS 'Operational data written by services (Grafana alert notifications)';
