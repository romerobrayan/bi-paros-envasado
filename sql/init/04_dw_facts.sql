-- =============================================================================
-- 04_dw_facts.sql — Fact tables
-- =============================================================================

-- -----------------------------------------------------------------------------
-- fact_produccion_turno
-- GRAIN: one shift form = one machine, one date, one shift, one operator and
-- one reference (source "Ingreso total" record), or one non-scheduled shift
-- declaration. Complement rows ("Ingreso subcódigo") are consolidated into
-- their parent form; their stoppages also live in fact_paro.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dw.fact_produccion_turno (
    registro_id                bigint   PRIMARY KEY,          -- degenerate: Excel source row
    fecha_sk                   integer  NOT NULL REFERENCES dw.dim_fecha(fecha_sk),
    turno_sk                   smallint NOT NULL REFERENCES dw.dim_turno(turno_sk),
    maquina_sk                 integer  NOT NULL REFERENCES dw.dim_maquina(maquina_sk),
    referencia_sk              integer  NOT NULL REFERENCES dw.dim_referencia(referencia_sk),
    operario_sk                integer  NOT NULL REFERENCES dw.dim_persona(persona_sk),
    estado_sk                  smallint NOT NULL REFERENCES dw.dim_estado_turno(estado_sk),
    tipo_registro              text     NOT NULL CHECK (tipo_registro IN ('PRODUCCION','NO_PROGRAMADO')),
    horas_trabajadas           numeric(6,2) NOT NULL DEFAULT 0 CHECK (horas_trabajadas BETWEEN 0 AND 24),
    horas_no_programadas       numeric(6,2) NOT NULL DEFAULT 0 CHECK (horas_no_programadas >= 0),
    horas_paro_planificado     numeric(10,5) NOT NULL DEFAULT 0 CHECK (horas_paro_planificado >= 0),
    horas_paro_disponibilidad  numeric(10,5) NOT NULL DEFAULT 0 CHECK (horas_paro_disponibilidad >= 0),
    horas_paro_calidad         numeric(10,5) NOT NULL DEFAULT 0 CHECK (horas_paro_calidad >= 0),
    horas_paro_total           numeric(10,5) GENERATED ALWAYS AS
                               (horas_paro_planificado + horas_paro_disponibilidad + horas_paro_calidad) STORED,
    horas_planificadas         numeric(10,5) NOT NULL DEFAULT 0 CHECK (horas_planificadas >= 0),   -- PPT
    horas_operativas           numeric(10,5) NOT NULL DEFAULT 0 CHECK (horas_operativas >= 0),     -- run time
    pacas_producidas           numeric(10,1) NOT NULL DEFAULT 0 CHECK (pacas_producidas >= 0),
    pacas_hora_ideal           numeric(8,3),                                                      -- NULL = not computable
    pacas_ideales              numeric(10,2),
    n_complementos             smallint NOT NULL DEFAULT 0,
    es_atipico                 boolean  NOT NULL DEFAULT false,
    paro_excede_turno          boolean  NOT NULL DEFAULT false,
    incluir_en_rendimiento     boolean  NOT NULL DEFAULT false
);
COMMENT ON TABLE dw.fact_produccion_turno IS
 'Grain: one shift production form (machine x date x shift x operator x reference) or one non-scheduled shift declaration';
COMMENT ON COLUMN dw.fact_produccion_turno.incluir_en_rendimiento IS
 'true when the ideal rate is known and the row is not an outlier; outliers are excluded ONLY from Performance';

-- -----------------------------------------------------------------------------
-- fact_paro
-- GRAIN: one stoppage cause inside one source record = record x code (01–18)
-- x subcode. Produced by unpivoting the 18 wide code columns.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dw.fact_paro (
    paro_id                 bigserial PRIMARY KEY,
    registro_id             bigint   NOT NULL,                     -- degenerate: Excel source row
    registro_padre_id       bigint   REFERENCES dw.fact_produccion_turno(registro_id),
    fecha_sk                integer  NOT NULL REFERENCES dw.dim_fecha(fecha_sk),
    turno_sk                smallint NOT NULL REFERENCES dw.dim_turno(turno_sk),
    maquina_sk              integer  NOT NULL REFERENCES dw.dim_maquina(maquina_sk),
    referencia_sk           integer  NOT NULL REFERENCES dw.dim_referencia(referencia_sk),
    operario_sk             integer  NOT NULL REFERENCES dw.dim_persona(persona_sk),
    persona_involucrada_sk  integer  NOT NULL REFERENCES dw.dim_persona(persona_sk),   -- role-playing
    causa_sk                integer  NOT NULL REFERENCES dw.dim_causa_paro(causa_sk),
    agente_involucrado      text,                                  -- only for code 05
    minutos_paro            numeric(8,2) NOT NULL CHECK (minutos_paro > 0),
    horas_paro              numeric(12,6) NOT NULL CHECK (horas_paro > 0),
    evento_falla            smallint NOT NULL DEFAULT 0 CHECK (evento_falla IN (0,1)),
    CONSTRAINT uq_paro_registro_causa UNIQUE (registro_id, causa_sk)
);
COMMENT ON TABLE dw.fact_paro IS 'Grain: one stoppage cause within one source record (unpivot of the 18 code columns)';

-- -----------------------------------------------------------------------------
-- fact_produccion_hora — near-real-time process (fed by the simulator)
-- GRAIN: one machine-hour = machine x simulated hour.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dw.fact_produccion_hora (
    hora_id                  bigserial   PRIMARY KEY,
    ts                       timestamptz NOT NULL DEFAULT now(),   -- wall-clock time of the tick (Grafana time axis)
    hora_simulada            timestamp   NOT NULL,                 -- simulated plant clock
    fecha_sk                 integer     NOT NULL REFERENCES dw.dim_fecha(fecha_sk),
    hora_dia                 smallint    NOT NULL CHECK (hora_dia BETWEEN 0 AND 23),
    turno_sk                 smallint    NOT NULL REFERENCES dw.dim_turno(turno_sk),
    maquina_sk               integer     NOT NULL REFERENCES dw.dim_maquina(maquina_sk),
    referencia_sk            integer     NOT NULL REFERENCES dw.dim_referencia(referencia_sk),
    causa_principal_sk       integer     REFERENCES dw.dim_causa_paro(causa_sk),
    modo_simulacion          text        NOT NULL,
    minutos_planificados     numeric(5,1) NOT NULL CHECK (minutos_planificados BETWEEN 0 AND 60),
    minutos_paro_no_planif   numeric(5,1) NOT NULL CHECK (minutos_paro_no_planif BETWEEN 0 AND 60),
    minutos_operativos       numeric(5,1) NOT NULL CHECK (minutos_operativos BETWEEN 0 AND 60),
    pacas                    numeric(8,1) NOT NULL CHECK (pacas >= 0),
    pacas_ideales            numeric(8,2) NOT NULL CHECK (pacas_ideales >= 0),
    pacas_meta               numeric(8,2) NOT NULL,
    disponibilidad           numeric(6,4),
    rendimiento              numeric(6,4),
    calidad                  numeric(6,4),
    oee                      numeric(6,4),
    CONSTRAINT uq_hora_maquina UNIQUE (maquina_sk, hora_simulada)
);
COMMENT ON TABLE dw.fact_produccion_hora IS 'Grain: one machine x one simulated hour (near real time, Grafana)';

-- -----------------------------------------------------------------------------
-- Simulator control and alert sink
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sim.control (
    maquina_nk    text PRIMARY KEY,
    modo          text NOT NULL DEFAULT 'normal' CHECK (modo IN ('normal','falla','lenta','parada')),
    actualizado   timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE sim.control IS 'Change modo from DBeaver to force a scenario live: normal | falla | lenta | parada';

CREATE TABLE IF NOT EXISTS sim.reloj (
    id            smallint PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    hora_simulada timestamp NOT NULL
);

CREATE TABLE IF NOT EXISTS ops.alertas_recibidas (
    alerta_id     bigserial PRIMARY KEY,
    recibida_en   timestamptz NOT NULL DEFAULT now(),
    estado        text,
    regla         text,
    maquina       text,
    valor         text,
    payload       jsonb
);
