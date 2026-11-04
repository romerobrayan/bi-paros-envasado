-- =============================================================================
-- 03_dw_dimensions.sql — Dimensions of the dimensional model
-- Surrogate keys (SK) are integers; natural keys (NK) are kept with a UNIQUE
-- constraint. Special members: -1 = "No registrado" (missing in source),
-- 0 = "No aplica" (the attribute does not apply to the row).
-- =============================================================================

-- -----------------------------------------------------------------------------
-- dim_fecha — calendar dimension BUILT BY US (not present in the source).
-- Generated with generate_series + Colombian public holidays (Ley 51/1983,
-- "Ley Emiliani") computed from the Easter date.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dw.dim_fecha (
    fecha_sk          integer     PRIMARY KEY,           -- yyyymmdd
    fecha             date        NOT NULL UNIQUE,
    dia               smallint    NOT NULL,
    dia_semana        smallint    NOT NULL CHECK (dia_semana BETWEEN 1 AND 7),  -- ISO: 1 = lunes
    nombre_dia        text        NOT NULL,
    semana_iso        smallint    NOT NULL,
    mes               smallint    NOT NULL CHECK (mes BETWEEN 1 AND 12),
    nombre_mes        text        NOT NULL,
    trimestre         smallint    NOT NULL CHECK (trimestre BETWEEN 1 AND 4),
    anio              smallint    NOT NULL,
    anio_mes          char(7)     NOT NULL,                -- 'YYYY-MM' (sortable label)
    es_fin_de_semana  boolean     NOT NULL,
    es_festivo        boolean     NOT NULL DEFAULT false,
    nombre_festivo    text,
    es_dia_habil      boolean     GENERATED ALWAYS AS (NOT es_fin_de_semana AND NOT es_festivo) STORED
);
COMMENT ON TABLE dw.dim_fecha IS 'Calendar dimension built by the team. Hierarchy: Año > Trimestre > Mes > Día';

-- Easter Sunday (anonymous Gregorian algorithm, Meeus/Jones/Butcher)
CREATE OR REPLACE FUNCTION etl.fn_domingo_pascua(p_anio int) RETURNS date
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE a int; b int; c int; d int; e int; f int; g int; h int; i int; k int; l int; m int; mes int; dia int;
BEGIN
    a := p_anio % 19;  b := p_anio / 100;  c := p_anio % 100;
    d := b / 4;  e := b % 4;  f := (b + 8) / 25;  g := (b - f + 1) / 3;
    h := (19*a + b - d - g + 15) % 30;
    i := c / 4;  k := c % 4;
    l := (32 + 2*e + 2*i - h - k) % 7;
    m := (a + 11*h + 22*l) / 451;
    mes := (h + l - 7*m + 114) / 31;
    dia := ((h + l - 7*m + 114) % 31) + 1;
    RETURN make_date(p_anio, mes, dia);
END $$;

-- Next Monday (or the same day if it is already Monday): Ley Emiliani rule
CREATE OR REPLACE FUNCTION etl.fn_siguiente_lunes(p_fecha date) RETURNS date
LANGUAGE sql IMMUTABLE AS $$
    SELECT p_fecha + ((8 - EXTRACT(ISODOW FROM p_fecha)::int) % 7);
$$;

-- Colombian public holidays for one year
CREATE OR REPLACE FUNCTION etl.fn_festivos_co(p_anio int)
RETURNS TABLE (fecha date, nombre text)
LANGUAGE sql IMMUTABLE AS $$
    WITH p AS (SELECT etl.fn_domingo_pascua(p_anio) AS pascua)
    -- fixed holidays (not moved)
    SELECT make_date(p_anio, 1, 1),   'Año Nuevo'                  UNION ALL
    SELECT make_date(p_anio, 5, 1),   'Día del Trabajo'            UNION ALL
    SELECT make_date(p_anio, 7, 20),  'Día de la Independencia'    UNION ALL
    SELECT make_date(p_anio, 8, 7),   'Batalla de Boyacá'          UNION ALL
    SELECT make_date(p_anio, 12, 8),  'Inmaculada Concepción'      UNION ALL
    SELECT make_date(p_anio, 12, 25), 'Navidad'                    UNION ALL
    -- Ley Emiliani: moved to the next Monday
    SELECT etl.fn_siguiente_lunes(make_date(p_anio, 1, 6)),   'Reyes Magos'                UNION ALL
    SELECT etl.fn_siguiente_lunes(make_date(p_anio, 3, 19)),  'San José'                   UNION ALL
    SELECT etl.fn_siguiente_lunes(make_date(p_anio, 6, 29)),  'San Pedro y San Pablo'      UNION ALL
    SELECT etl.fn_siguiente_lunes(make_date(p_anio, 8, 15)),  'Asunción de la Virgen'      UNION ALL
    SELECT etl.fn_siguiente_lunes(make_date(p_anio, 10, 12)), 'Día de la Raza'             UNION ALL
    SELECT etl.fn_siguiente_lunes(make_date(p_anio, 11, 1)),  'Todos los Santos'           UNION ALL
    SELECT etl.fn_siguiente_lunes(make_date(p_anio, 11, 11)), 'Independencia de Cartagena' UNION ALL
    -- Easter-based holidays
    SELECT pascua - 3,  'Jueves Santo'     FROM p UNION ALL
    SELECT pascua - 2,  'Viernes Santo'    FROM p UNION ALL
    SELECT pascua + 43, 'Ascensión del Señor' FROM p UNION ALL   -- Thursday +39 moved to Monday
    SELECT pascua + 64, 'Corpus Christi'      FROM p UNION ALL   -- Thursday +60 moved to Monday
    SELECT pascua + 71, 'Sagrado Corazón'     FROM p;            -- Friday +68 moved to Monday
$$;

CREATE OR REPLACE PROCEDURE etl.sp_cargar_dim_fecha(p_desde date, p_hasta date)
LANGUAGE plpgsql AS $$
BEGIN
    INSERT INTO dw.dim_fecha (fecha_sk, fecha, dia, dia_semana, nombre_dia, semana_iso, mes, nombre_mes,
                              trimestre, anio, anio_mes, es_fin_de_semana)
    SELECT to_char(d, 'YYYYMMDD')::int,
           d::date,
           EXTRACT(DAY FROM d)::smallint,
           EXTRACT(ISODOW FROM d)::smallint,
           (ARRAY['Lunes','Martes','Miércoles','Jueves','Viernes','Sábado','Domingo'])[EXTRACT(ISODOW FROM d)::int],
           EXTRACT(WEEK FROM d)::smallint,
           EXTRACT(MONTH FROM d)::smallint,
           (ARRAY['Enero','Febrero','Marzo','Abril','Mayo','Junio','Julio','Agosto','Septiembre',
                  'Octubre','Noviembre','Diciembre'])[EXTRACT(MONTH FROM d)::int],
           EXTRACT(QUARTER FROM d)::smallint,
           EXTRACT(YEAR FROM d)::smallint,
           to_char(d, 'YYYY-MM'),
           EXTRACT(ISODOW FROM d) IN (6, 7)
    FROM generate_series(p_desde, p_hasta, interval '1 day') AS g(d)
    ON CONFLICT (fecha) DO NOTHING;

    UPDATE dw.dim_fecha f
       SET es_festivo = true, nombre_festivo = h.nombre
      FROM (SELECT (etl.fn_festivos_co(y)).* FROM generate_series(EXTRACT(YEAR FROM p_desde)::int,
                                                                 EXTRACT(YEAR FROM p_hasta)::int) AS y) h
     WHERE f.fecha = h.fecha;
END $$;

-- -----------------------------------------------------------------------------
-- dim_turno — shifts. Hierarchy: Esquema > Turno
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dw.dim_turno (
    turno_sk      smallint PRIMARY KEY,
    turno_nk      text     NOT NULL UNIQUE,
    hora_inicio   time,
    hora_fin      time,
    duracion_h    numeric(4,1) CHECK (duracion_h IS NULL OR duracion_h BETWEEN 0 AND 24),
    esquema       text     NOT NULL,     -- '3x8', '2x12', '1x10.5', 'N/A'
    es_nocturno   boolean  NOT NULL DEFAULT false
);

-- -----------------------------------------------------------------------------
-- dim_maquina — SCD TYPE 2 on the ideal speed (units/minute).
-- A speed change closes the current version and opens a new one, so the
-- historical Performance is always computed with the speed in force that day.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dw.dim_maquina (
    maquina_sk           serial   PRIMARY KEY,
    maquina_nk           text     NOT NULL,
    planta               text     NOT NULL DEFAULT 'Planta vinilos y témperas',
    linea                text     NOT NULL DEFAULT 'Envasado de vinilos',
    velocidad_ideal_upm  numeric(6,1) NOT NULL CHECK (velocidad_ideal_upm >= 0),
    vigente_desde        date     NOT NULL,
    vigente_hasta        date     NOT NULL DEFAULT DATE '9999-12-31',
    es_actual            boolean  NOT NULL DEFAULT true,
    motivo_version       text,
    CONSTRAINT ck_maquina_vigencia CHECK (vigente_hasta > vigente_desde),
    CONSTRAINT uq_maquina_version UNIQUE (maquina_nk, vigente_desde)
);
-- only one current version per machine
CREATE UNIQUE INDEX IF NOT EXISTS uq_maquina_actual ON dw.dim_maquina (maquina_nk) WHERE es_actual;
COMMENT ON TABLE dw.dim_maquina IS 'SCD Type 2 on velocidad_ideal_upm. Hierarchy: Planta > Línea > Máquina';

-- -----------------------------------------------------------------------------
-- dim_referencia — SKU. Hierarchy: Marca > Presentación (cc) > Referencia
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dw.dim_referencia (
    referencia_sk        integer  PRIMARY KEY,
    referencia_nk        text     NOT NULL UNIQUE,      -- normalized name
    marca                text     NOT NULL,
    presentacion_cc      smallint,
    presentacion         text     NOT NULL,             -- e.g. '22cc' or 'Sin dato'
    num_colores          smallint,
    unidades_por_paca    integer,                      -- most frequent value across machines
    en_catalogo          boolean  NOT NULL DEFAULT false
);

-- -----------------------------------------------------------------------------
-- dim_persona — pseudonymized people (operators and maintenance staff).
-- ROLE-PLAYING: used as "operario" and as "persona involucrada" in the facts.
-- Real names never reach the warehouse (Ley 1581 de 2012).
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dw.dim_persona (
    persona_sk     integer PRIMARY KEY,
    seudonimo      text    NOT NULL UNIQUE,             -- 'PER-1a2b3c'
    rol_principal  text    NOT NULL                     -- 'Operaria/o', 'Mantenimiento', 'Mixto', 'N/A'
);

-- -----------------------------------------------------------------------------
-- dim_causa_paro — stoppage hierarchy flattened to fixed depth:
--   Área de impacto > Código (01–18) > Sistema / subcódigo > Componente
-- Missing levels are filled with 'Sin subcódigo' / 'Sin detalle' (ragged → fixed).
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dw.dim_causa_paro (
    causa_sk           integer  PRIMARY KEY,
    causa_nk           text     NOT NULL UNIQUE,        -- '05', '05|5.2', '01|1.2.C'
    area_impacto       text     NOT NULL,
    codigo             smallint NOT NULL CHECK (codigo BETWEEN 1 AND 18),
    codigo_txt         char(4)  NOT NULL,               -- '[05]'
    codigo_descripcion text     NOT NULL,
    codigo_label       text     NOT NULL,               -- '[05] Ajuste operativo'
    sistema_clave      text,
    sistema            text     NOT NULL,
    componente_clave   text,
    componente         text     NOT NULL,
    nivel_detalle      smallint NOT NULL CHECK (nivel_detalle BETWEEN 1 AND 3),
    clase_oee          text     NOT NULL CHECK (clase_oee IN ('Planificado','Disponibilidad','Calidad')),
    es_planificado     boolean  NOT NULL
);
COMMENT ON TABLE dw.dim_causa_paro IS 'Flattened ragged hierarchy Área > Código > Sistema > Componente. clase_oee drives the OEE time model';

-- -----------------------------------------------------------------------------
-- dim_estado_turno — unifies the two "Tipo de paro" coding schemes (old/new)
-- Hierarchy: Categoría > Estado
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dw.dim_estado_turno (
    estado_sk      smallint PRIMARY KEY,
    estado_nk      text     NOT NULL UNIQUE,
    categoria      text     NOT NULL,                   -- 'Turno trabajado', 'No programado (comercial)', 'Turno perdido (planta)', 'No registrado'
    codigo_unificado text
);
