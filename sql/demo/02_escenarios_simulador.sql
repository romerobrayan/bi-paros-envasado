-- =============================================================================
-- Live demo script (DBeaver): force scenarios and watch Grafana react.
-- With SIM_TICK_SECONDS=30, one simulated hour = 30 s; the alert needs 2 bad
-- hours, so it fires about 1–1.5 minutes after the change.
-- =============================================================================

-- 0. current state
SELECT * FROM sim.control ORDER BY maquina_nk;
SELECT maquina_nk, estado, modo_simulacion, ROUND(oee * 100, 1) AS oee_pct, causa_principal
FROM dw.vw_rt_estado_actual;

-- 1. electromechanical failure on Vinilos_2  -> OEE ~15–35%, alert fires
UPDATE sim.control SET modo = 'falla', actualizado = now() WHERE maquina_nk = 'Vinilos_2';

-- 2. slow line on Vinilos_3 (dosing-system adjustments)  -> OEE ~35–50%
UPDATE sim.control SET modo = 'lenta', actualizado = now() WHERE maquina_nk = 'Vinilos_3';

-- 3. no raw material on Vinilos_4  -> state PARADA, OEE 0%
UPDATE sim.control SET modo = 'parada', actualizado = now() WHERE maquina_nk = 'Vinilos_4';

-- 4. back to normal  -> alert resolves after 2 good hours
UPDATE sim.control SET modo = 'normal', actualizado = now();

-- 5. notifications received from Grafana
SELECT alerta_id, recibida_en, estado, maquina, regla, valor FROM ops.alertas_recibidas ORDER BY alerta_id DESC;

-- Reset the near-real-time data (keeps the historical warehouse intact)
-- TRUNCATE dw.fact_produccion_hora; DELETE FROM sim.reloj; TRUNCATE ops.alertas_recibidas;
