#!/bin/bash
# =============================================================================
# 99_roles.sh — Least-privilege roles. Runs last in /docker-entrypoint-initdb.d
# Passwords come from environment variables (.env), never from the repo.
#   etl_user      : read/write on stg, dw, etl, sim, ops (ETL, simulator, alert sink)
#   grafana_ro    : read-only on dw, sim, ops (Grafana datasource)
#   powerbi_ro    : read-only on dw (Power BI Desktop on the host)
# =============================================================================
set -euo pipefail

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    DO \$\$
    BEGIN
        IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '${ETL_DB_USER}') THEN
            CREATE ROLE ${ETL_DB_USER} LOGIN PASSWORD '${ETL_DB_PASSWORD}';
        END IF;
        IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '${GRAFANA_DB_USER}') THEN
            CREATE ROLE ${GRAFANA_DB_USER} LOGIN PASSWORD '${GRAFANA_DB_PASSWORD}';
        END IF;
        IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '${POWERBI_DB_USER}') THEN
            CREATE ROLE ${POWERBI_DB_USER} LOGIN PASSWORD '${POWERBI_DB_PASSWORD}';
        END IF;
    END \$\$;

    -- ETL writer
    GRANT USAGE ON SCHEMA stg, dw, etl, sim, ops TO ${ETL_DB_USER};
    GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE ON ALL TABLES IN SCHEMA stg, dw, etl, sim, ops TO ${ETL_DB_USER};
    GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA dw, etl, ops TO ${ETL_DB_USER};
    GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA etl TO ${ETL_DB_USER};
    GRANT EXECUTE ON PROCEDURE etl.sp_cargar_dim_fecha(date, date) TO ${ETL_DB_USER};

    -- Grafana: read-only on the warehouse, simulator control and alerts
    GRANT USAGE ON SCHEMA dw, sim, ops TO ${GRAFANA_DB_USER};
    GRANT SELECT ON ALL TABLES IN SCHEMA dw, sim, ops TO ${GRAFANA_DB_USER};

    -- Power BI: read-only on the warehouse only (no staging, no ETL metadata)
    GRANT USAGE ON SCHEMA dw TO ${POWERBI_DB_USER};
    GRANT SELECT ON ALL TABLES IN SCHEMA dw TO ${POWERBI_DB_USER};

    -- Seed of the simulator: one control row per machine and the simulated clock
    INSERT INTO sim.control (maquina_nk) VALUES ('Vinilos_1'),('Vinilos_2'),('Vinilos_3'),('Vinilos_4')
    ON CONFLICT DO NOTHING;
EOSQL

echo "Roles created: ${ETL_DB_USER}, ${GRAFANA_DB_USER}, ${POWERBI_DB_USER}"
