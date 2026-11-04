"""Hour-by-hour simulator (near real time) — python -m etl.simulator

Every SIM_TICK_SECONDS the plant clock advances ONE hour and one row per machine
is written to dw.fact_produccion_hora. The behavior of each machine is driven by
sim.control.modo, which can be changed live from DBeaver:

    UPDATE sim.control SET modo = 'falla', actualizado = now() WHERE maquina_nk = 'Vinilos_2';

    normal : historical-like behavior (OEE around 70–85%)
    falla  : electromechanical failure, 30–50 unplanned minutes/hour (code 01)
    lenta  : dosing-system adjustments, speed at 45–60% (code 05 | 5.2)
    parada : no raw material, the whole hour is lost (code 14)
"""
from __future__ import annotations

import random
import time
from datetime import datetime, timedelta

import psycopg2

from .config import settings

# planned breaks of the shift (hour of day -> planned minutes, cause)
PLANNED_BREAKS = {9: (10, "16"), 12: (15, "16"), 17: (10, "17"), 20: (15, "16"), 1: (10, "17"), 4: (15, "16")}
NORMAL_CAUSES = [("05|5.2", 0.35), ("06", 0.25), ("07", 0.15), ("10", 0.10), ("05|5.5", 0.10), ("14", 0.05)]
TARGET_FACTOR = 0.85          # hourly target = 85% of the ideal output


def turno_sk(hour: int) -> int:
    if 6 <= hour < 14:
        return 1
    if 14 <= hour < 22:
        return 2
    return 3


def connect():
    for i in range(60):
        try:
            conn = psycopg2.connect(settings.dsn())
            conn.autocommit = True
            return conn
        except Exception as exc:  # noqa: BLE001
            print(f"Waiting for database ({i + 1}/60): {exc.__class__.__name__}")
            time.sleep(2)
    raise RuntimeError("Database not reachable")


def load_context(cur) -> dict:
    cur.execute("SELECT causa_nk, causa_sk FROM dw.dim_causa_paro")
    causas = dict(cur.fetchall())
    if not causas:
        raise RuntimeError("Dimensions are empty: run the ETL first")
    # most produced reference (with a known rate) per machine in the latest year
    cur.execute("""
        WITH r AS (
            SELECT m.maquina_nk, p.referencia_sk, SUM(p.pacas_producidas) pacas,
                   AVG(p.pacas_hora_ideal) rate,
                   ROW_NUMBER() OVER (PARTITION BY m.maquina_nk ORDER BY SUM(p.pacas_producidas) DESC) rn
            FROM dw.fact_produccion_turno p
            JOIN dw.dim_maquina m ON m.maquina_sk = p.maquina_sk
            JOIN dw.dim_fecha f   ON f.fecha_sk   = p.fecha_sk
            WHERE p.pacas_hora_ideal IS NOT NULL AND f.anio >= 2024
            GROUP BY m.maquina_nk, p.referencia_sk)
        SELECT maquina_nk, referencia_sk FROM r WHERE rn = 1""")
    refs = dict(cur.fetchall())
    return {"causas": causas, "refs": refs}


def machines(cur, refs: dict) -> list[dict]:
    """Current SCD2 version of each machine + its simulated reference and ideal rate.
    Read on every tick, so a new SCD2 version (speed change) or a new modo applies immediately."""
    out = []
    for nk, ref_sk in refs.items():
        cur.execute("""
            SELECT m.maquina_sk, m.velocidad_ideal_upm, COALESCE(c.modo, 'normal'), r.unidades_por_paca
            FROM dw.dim_maquina m
            LEFT JOIN sim.control c ON c.maquina_nk = m.maquina_nk
            JOIN dw.dim_referencia r ON r.referencia_sk = %s
            WHERE m.es_actual AND m.maquina_nk = %s""", (ref_sk, nk))
        row = cur.fetchone()
        if row:
            sk, upm, modo, upaca = row
            out.append(dict(nk=nk, sk=sk, modo=modo, ref_sk=ref_sk,
                            rate=float(upm) * 60 / float(upaca or 600)))
    return out


def simulate_hour(m: dict, hour: int, causas: dict, rng: random.Random) -> dict:
    planned, planned_cause = PLANNED_BREAKS.get(hour, (rng.choice([0, 0, 3, 5]), "17"))
    quality = 0.0
    if m["modo"] == "falla":
        unplanned, cause, perf = rng.uniform(30, 50), rng.choice(["01|1.2.C", "01|1.6", "01|1.7", "01|1.4.A"]), rng.uniform(0.75, 0.9)
    elif m["modo"] == "lenta":
        unplanned, cause, perf = max(0.0, rng.gauss(8, 4)), "05|5.2", rng.uniform(0.45, 0.6)
    elif m["modo"] == "parada":
        unplanned, cause, perf = 60.0 - planned, "14", 0.0
    else:
        unplanned = max(0.0, rng.gauss(6, 4))
        cause = rng.choices([c for c, _ in NORMAL_CAUSES], weights=[w for _, w in NORMAL_CAUSES])[0]
        perf = min(1.02, max(0.6, rng.gauss(0.9, 0.05)))
        quality = rng.choice([0, 0, 0, 0, 1, 2])
    ppt = 60.0 - planned
    unplanned = min(unplanned, ppt)
    run = ppt - unplanned
    quality = min(quality, run)
    ideal = run / 60 * m["rate"]
    pacas = round(ideal * perf, 1)   # fractional bales: an open bale at the end of the hour
    a = run / ppt if ppt else None
    p = pacas / ideal if ideal else None
    q = 1 - quality / run if run else None
    oee = a * p * q if None not in (a, p, q) else 0.0
    main_cause = cause if unplanned >= 1 else planned_cause if planned else None
    return dict(minutos_planificados=round(planned, 1), minutos_paro_no_planif=round(unplanned, 1),
                minutos_operativos=round(run, 1), pacas=pacas, pacas_ideales=round(ideal, 2),
                pacas_meta=round(ppt / 60 * m["rate"] * TARGET_FACTOR, 2),
                disponibilidad=a, rendimiento=p, calidad=q, oee=oee if run else 0.0,
                causa_principal_sk=causas.get(main_cause) if main_cause else None)


def insert(cur, m: dict, clock: datetime, ts: datetime, values: dict) -> None:
    cur.execute("""
        INSERT INTO dw.fact_produccion_hora (ts, hora_simulada, fecha_sk, hora_dia, turno_sk, maquina_sk,
            referencia_sk, causa_principal_sk, modo_simulacion, minutos_planificados, minutos_paro_no_planif,
            minutos_operativos, pacas, pacas_ideales, pacas_meta, disponibilidad, rendimiento, calidad, oee)
        VALUES (%(ts)s, %(clock)s, %(fecha_sk)s, %(hour)s, %(turno)s, %(sk)s, %(ref)s, %(causa_principal_sk)s,
                %(modo)s, %(minutos_planificados)s, %(minutos_paro_no_planif)s, %(minutos_operativos)s, %(pacas)s,
                %(pacas_ideales)s, %(pacas_meta)s, %(disponibilidad)s, %(rendimiento)s, %(calidad)s, %(oee)s)
        ON CONFLICT (maquina_sk, hora_simulada) DO NOTHING""",
                dict(values, ts=ts, clock=clock, fecha_sk=int(clock.strftime("%Y%m%d")), hour=clock.hour,
                     turno=turno_sk(clock.hour), sk=m["sk"], ref=m["ref_sk"], modo=m["modo"]))


def run() -> None:
    rng = random.Random(settings.sim_seed)
    conn = connect()
    cur = conn.cursor()
    ctx = None
    while ctx is None:
        try:
            ctx = load_context(cur)
        except Exception as exc:  # noqa: BLE001  (ETL may still be running)
            print(f"Simulator waiting for the ETL: {exc}")
            time.sleep(5)

    cur.execute("SELECT hora_simulada FROM sim.reloj WHERE id = 1")
    row = cur.fetchone()
    tick = timedelta(seconds=settings.sim_tick_seconds)
    if row is None:
        # warm-up: backfill 24 simulated hours so dashboards are not empty at start
        clock = datetime.now().replace(minute=0, second=0, microsecond=0) - timedelta(hours=24)
        now = datetime.now().astimezone()
        for i in range(24):
            for m in machines(cur, ctx["refs"]):
                m["modo"] = "normal"
                insert(cur, m, clock, now - tick * (24 - i), simulate_hour(m, clock.hour, ctx["causas"], rng))
            clock += timedelta(hours=1)
        cur.execute("INSERT INTO sim.reloj (id, hora_simulada) VALUES (1, %s)", (clock,))
    else:
        clock = row[0]

    print(f"Simulator running: 1 simulated hour every {settings.sim_tick_seconds}s")
    while True:
        clock += timedelta(hours=1)
        now = datetime.now().astimezone()
        for m in machines(cur, ctx["refs"]):
            v = simulate_hour(m, clock.hour, ctx["causas"], rng)
            insert(cur, m, clock, now, v)
            print(f"{clock:%Y-%m-%d %H:00} {m['nk']:<10} modo={m['modo']:<7} OEE={v['oee']:.0%} pacas={v['pacas']}")
        cur.execute("UPDATE sim.reloj SET hora_simulada = %s WHERE id = 1", (clock,))
        time.sleep(settings.sim_tick_seconds)


if __name__ == "__main__":
    run()
