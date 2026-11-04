-- =============================================================================
-- SCD Type 2 demo: Vinilos_3 gets a new dosing head and its ideal speed goes
-- from 80 to 95 units/minute starting today.
--   * The historical facts keep pointing to version 1 (80 upm), so the 2023–2025
--     Performance does NOT change.
--   * The simulator reads the CURRENT version on every tick, so new hours use 95 upm.
-- Run as the admin user in DBeaver.
-- =============================================================================
BEGIN;

-- 1. close the current version
UPDATE dw.dim_maquina
   SET vigente_hasta = CURRENT_DATE,
       es_actual     = false
 WHERE maquina_nk = 'Vinilos_3' AND es_actual;

-- 2. open the new version
INSERT INTO dw.dim_maquina (maquina_nk, velocidad_ideal_upm, vigente_desde, es_actual, motivo_version)
VALUES ('Vinilos_3', 95, CURRENT_DATE, true, 'Cambio de cabezal dosificador (demo SCD2)');

COMMIT;

-- 3. evidence: two versions, historical facts still on version 1
SELECT maquina_sk, maquina_nk, velocidad_ideal_upm, vigente_desde, vigente_hasta, es_actual, motivo_version
FROM dw.dim_maquina WHERE maquina_nk = 'Vinilos_3' ORDER BY vigente_desde;

SELECT m.maquina_sk, m.velocidad_ideal_upm, COUNT(*) AS filas_historicas
FROM dw.fact_produccion_turno p JOIN dw.dim_maquina m ON m.maquina_sk = p.maquina_sk
WHERE m.maquina_nk = 'Vinilos_3' GROUP BY 1, 2;

SELECT m.maquina_sk, m.velocidad_ideal_upm, COUNT(*) AS horas_simuladas
FROM dw.fact_produccion_hora h JOIN dw.dim_maquina m ON m.maquina_sk = h.maquina_sk
WHERE m.maquina_nk = 'Vinilos_3' GROUP BY 1, 2;

-- Undo (only for rehearsals):
-- DELETE FROM dw.fact_produccion_hora WHERE maquina_sk = (SELECT maquina_sk FROM dw.dim_maquina WHERE maquina_nk='Vinilos_3' AND es_actual);
-- DELETE FROM dw.dim_maquina WHERE maquina_nk = 'Vinilos_3' AND es_actual;
-- UPDATE dw.dim_maquina SET vigente_hasta = '9999-12-31', es_actual = true WHERE maquina_nk = 'Vinilos_3';
