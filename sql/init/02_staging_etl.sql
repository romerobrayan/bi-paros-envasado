-- =============================================================================
-- 02_staging_etl.sql — Staging tables and ETL metadata tables
-- Staging keeps every source column as TEXT: the ETL never fails on a badly
-- typed cell, and the raw value remains auditable after cleaning.
-- =============================================================================

-- Raw copy of sheet "Base De Datos" (table T_baseDeDatos). source_row = Excel row.
CREATE TABLE IF NOT EXISTS stg.base_datos_raw (
    source_row                    integer PRIMARY KEY,
    fecha                         text,
    mes                           text,
    anio                          text,
    maquina                       text,
    operario                      text,
    referencia                    text,
    unidades_por_minuto           text,
    unidad_por_display            text,
    display_por_paca              text,
    pacas_producidas              text,
    horas_trabajadas              text,
    turno                         text,
    horas_no_trabajadas           text,
    tipo_de_paro                  text,
    observaciones_de_paro         text,
    cod01_min text, subcod01 text, cod01_h text,
    cod02_min text, cod02_h text,
    cod03_min text, subcod03 text, cod03_h text,
    cod04_min text, cod04_h text,
    cod05_min text, subcod05 text, cod05_h text,
    area_involucrada_cod05        text,
    personal_involucrado          text,
    cod06_min text, cod06_h text,
    cod07_min text, cod07_h text,
    cod08_min text, cod08_h text,
    cod09_min text, cod09_h text,
    cod10_min text, cod10_h text,
    cod11_min text, cod11_h text,
    cod12_min text, cod12_h text,
    cod13_min text, cod13_h text,
    cod14_min text, cod14_h text,
    cod15_min text, cod15_h text,
    cod16_min text, cod16_h text,
    cod17_min text, cod17_h text,
    cod18_min text, cod18_h text,
    tiempo_de_paro                text,
    observaciones                 text,
    loaded_at                     timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE stg.base_datos_raw IS 'Raw copy of Excel table T_baseDeDatos (sheet "Base De Datos"); names are pseudonymized before landing here';

-- Catalogs read from sheet "Tablas Desplegables"
CREATE TABLE IF NOT EXISTS stg.cat_codigos (
    codigo        smallint PRIMARY KEY,
    paro          text,
    area_impacto  text,
    clave         text
);
CREATE TABLE IF NOT EXISTS stg.cat_subcodigos (
    codigo        smallint NOT NULL,
    clave         text     NOT NULL,
    descripcion   text,
    PRIMARY KEY (codigo, clave)
);
CREATE TABLE IF NOT EXISTS stg.cat_referencias (
    maquina            text NOT NULL,
    referencia         text NOT NULL,
    referencia_norm    text NOT NULL,
    num_colores        integer,
    display_por_paca   integer,
    unidades_por_paca  integer,
    unidades_por_minuto integer,
    PRIMARY KEY (maquina, referencia)
);

-- ETL metadata --------------------------------------------------------------
CREATE TABLE IF NOT EXISTS etl.run_log (
    run_id        serial PRIMARY KEY,
    started_at    timestamptz NOT NULL DEFAULT now(),
    finished_at   timestamptz,
    status        text NOT NULL DEFAULT 'RUNNING' CHECK (status IN ('RUNNING','OK','FAILED')),
    source_file   text,
    source_sha256 text,
    message       text
);

CREATE TABLE IF NOT EXISTS etl.dq_log (
    run_id         integer NOT NULL REFERENCES etl.run_log(run_id) ON DELETE CASCADE,
    rule_id        text    NOT NULL,
    dq_ref         text,
    regla          text    NOT NULL,
    accion         text    NOT NULL,
    filas_antes    integer,
    filas_afectadas integer NOT NULL,
    filas_despues  integer,
    PRIMARY KEY (run_id, rule_id)
);
COMMENT ON TABLE etl.dq_log IS 'One row per cleaning rule per run: rows before, affected and after';

CREATE TABLE IF NOT EXISTS etl.reconciliacion (
    run_id        integer NOT NULL REFERENCES etl.run_log(run_id) ON DELETE CASCADE,
    metrica       text    NOT NULL,
    valor_fuente  numeric(14,2) NOT NULL,
    valor_cargado numeric(14,2) NOT NULL,
    diferencia    numeric(14,2) GENERATED ALWAYS AS (valor_cargado - valor_fuente) STORED,
    explicacion   text,
    PRIMARY KEY (run_id, metrica)
);
COMMENT ON TABLE etl.reconciliacion IS 'Source totals vs loaded totals (hours, bales, stoppage time) with the reason for any difference';
