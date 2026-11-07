"""ETL entry point: python -m etl.main

Full refresh, reproducible from scratch:
  1. extract the Excel tables (no macros executed)
  2. pseudonymize people
  3. clean (rules R02..R11, each one logged with counts)
  4. transform: unpivot stoppages, link complement records, compute OEE time model
  5. load staging + dimensions + facts
  6. reconcile source totals vs loaded totals and store the result
"""
from __future__ import annotations

import glob
import hashlib
import os
import sys
import time

import pandas as pd

from . import load as L
from . import transform as T
from .config import settings


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def wait_for_db(dsn: str, attempts: int = 30):
    for i in range(attempts):
        try:
            return L.connect(dsn)
        except Exception as exc:  # noqa: BLE001
            print(f"Waiting for database ({i + 1}/{attempts}): {exc.__class__.__name__}")
            time.sleep(2)
    raise RuntimeError("Database not reachable")


def source_totals(base: pd.DataFrame) -> dict:
    num = lambda c: pd.to_numeric(base[c], errors="coerce").fillna(0).sum()  # noqa: E731
    return {
        "filas": len(base),
        "horas_trabajadas": num("horas_trabajadas"),
        "pacas": num("pacas_producidas"),
        "horas_no_trabajadas": num("horas_no_trabajadas"),
        "tiempo_paro": num("tiempo_de_paro"),
    }


def reconcile(conn, src: dict, dq: T.DQLog, base: pd.DataFrame, clean_df: pd.DataFrame) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute("""SELECT COUNT(*), COALESCE(SUM(horas_trabajadas),0), COALESCE(SUM(pacas_producidas),0),
                              COALESCE(SUM(horas_no_programadas),0), COALESCE(SUM(horas_paro_total),0),
                              COUNT(*) FILTER (WHERE es_atipico), COALESCE(SUM(pacas_producidas) FILTER (WHERE es_atipico),0)
                       FROM dw.fact_produccion_turno""")
        n_fpt, h_fpt, p_fpt, hn_fpt, paro_fpt, n_out, p_out = [float(x) for x in cur.fetchone()]
        cur.execute("SELECT COALESCE(SUM(horas_paro),0), COUNT(DISTINCT registro_id) FROM dw.fact_paro")
        paro_fp, _ = [float(x) for x in cur.fetchone()]
        cur.execute("""SELECT COALESCE(SUM(horas_paro),0), COUNT(DISTINCT registro_id) FROM dw.fact_paro
                       WHERE registro_padre_id IS NULL""")
        paro_orphan, n_orphan = [float(x) for x in cur.fetchone()]
        cur.execute("""SELECT COUNT(DISTINCT registro_id) FROM dw.fact_paro fp
                       WHERE NOT EXISTS (SELECT 1 FROM dw.fact_produccion_turno p WHERE p.registro_id = fp.registro_id)""")
        n_comp = float(cur.fetchone()[0])

    # contribution of removed rows (duplicates, empty, invalid date)
    removed = base[~base["source_row"].isin(clean_df["source_row"])]
    rem = source_totals(removed)
    dups = next(e for e in dq.entries if e["rule_id"] == "R03")["filas_afectadas"]
    empty = next(e for e in dq.entries if e["rule_id"] == "R11")["filas_afectadas"]

    return [
        dict(metrica="01 Filas (registros)", fuente=src["filas"], cargado=n_fpt + n_comp,
             explicacion=f"{int(n_fpt)} formularios en fact_produccion_turno + {int(n_comp)} registros complemento "
                         f"(solo en fact_paro). Diferencia = {dups} duplicados exactos + {empty} filas vacías eliminadas"),
        dict(metrica="02 Horas trabajadas", fuente=round(src["horas_trabajadas"], 2), cargado=round(h_fpt, 2),
             explicacion=f"Diferencia = horas de los duplicados eliminados ({rem['horas_trabajadas']:.2f} h)"),
        dict(metrica="03 Pacas producidas", fuente=round(src["pacas"], 2), cargado=round(p_fpt, 2),
             explicacion=f"Diferencia = pacas de los duplicados ({rem['pacas']:.0f}). Los {int(n_out)} atípicos "
                         f"({p_out:.0f} pacas) SE CONSERVAN en el total y solo se excluyen del Rendimiento"),
        dict(metrica="04 Horas no programadas", fuente=round(src["horas_no_trabajadas"], 2), cargado=round(hn_fpt, 2),
             explicacion=f"Diferencia = duplicados eliminados ({rem['horas_no_trabajadas']:.2f} h)"),
        dict(metrica="05 Tiempo de paro (fact_paro)", fuente=round(src["tiempo_paro"], 2), cargado=round(paro_fp, 2),
             explicacion=f"Diferencia = paro de los duplicados ({rem['tiempo_paro']:.2f} h). El unpivot conserva "
                         f"todo el tiempo de paro (±0.01 h por redondeo a 2 decimales)"),
        dict(metrica="06 Tiempo de paro (consolidado por formulario)", fuente=round(src["tiempo_paro"], 2),
             cargado=round(paro_fpt, 2),
             explicacion=f"Diferencia = duplicados ({rem['tiempo_paro']:.2f} h) + {int(n_orphan)} complementos sin "
                         f"formulario padre ({paro_orphan:.2f} h, siguen en fact_paro)"),
    ]


def resolve_source(path: str) -> str:
    """Use SOURCE_FILE if it exists; otherwise accept the only Excel found next to it.

    The workbook is not versioned (personal data), so after a fresh clone it is
    copied by hand into data/raw/ and its name may differ slightly.
    """
    if os.path.isfile(path):
        return path
    folder = os.path.dirname(path) or "."
    found = sorted(glob.glob(os.path.join(folder, "*.xls[mx]")))
    if len(found) == 1:
        print(f"SOURCE_FILE not found, using the only workbook in {folder}: {os.path.basename(found[0])}")
        return found[0]
    raise SystemExit(
        f"Source workbook not found: {path}\n"
        f"Copy 'SEGUIMIENTO TEMPERAS Y VINILOS Actividad.xlsm' into data/raw/ "
        f"(found {len(found)} workbooks there) and run: docker compose up -d")


def run() -> int:
    t0 = time.time()
    source_file = resolve_source(settings.source_file)
    print(f"Source: {source_file}")
    conn = wait_for_db(settings.dsn())
    conn.autocommit = False
    with conn.cursor() as cur:
        cur.execute("INSERT INTO etl.run_log (source_file, source_sha256) VALUES (%s, %s) RETURNING run_id",
                    (source_file, sha256(source_file)))
        run_id = cur.fetchone()[0]
    conn.commit()
    dq = T.DQLog()
    try:
        print("[1/6] Extract")
        raw = T.extract(source_file)
        cat = T.build_catalogs(raw)
        src = source_totals(raw["base"])
        print(f"      {src['filas']} rows in T_baseDeDatos")

        print("[2/6] Pseudonymize")
        base, people = T.pseudonymize(raw["base"], settings.pseudonym_salt, dq)

        print("[3/6] Clean")
        clean_df = T.clean(base, cat, dq)

        print("[4/6] Transform")
        causas = T.build_causas(cat)
        paros = T.unpivot_paros(clean_df, causas, dq)
        parent = T.link_complements(clean_df, dq)
        upm = L.dim_maquina(cat["refs"], settings.calendar_from).set_index("maquina_nk")["velocidad_ideal_upm"]
        prod = T.build_produccion(clean_df, paros, parent, cat["refs"], upm.to_dict(), dq)

        print("[5/6] Load")
        counts = L.load_all(conn, base, cat, clean_df, causas, paros, prod, people,
                            (settings.calendar_from, settings.calendar_to))
        for table, n in counts.items():
            print(f"      {table:<28} {n:>7}")

        print("[6/6] Reconcile")
        recon = reconcile(conn, src, dq, base, clean_df)
        for r in recon:
            print(f"      {r['metrica']:<48} fuente={r['fuente']:>12,.2f} cargado={r['cargado']:>12,.2f}")
        L.write_logs(conn, run_id, dq.entries, recon)
        with conn.cursor() as cur:
            cur.execute("UPDATE etl.run_log SET status='OK', finished_at=now(), message=%s WHERE run_id=%s",
                        (f"Loaded in {time.time() - t0:.1f}s", run_id))
        conn.commit()
        print(f"ETL OK (run_id={run_id}) in {time.time() - t0:.1f}s")
        return 0
    except Exception as exc:
        conn.rollback()
        with conn.cursor() as cur:
            cur.execute("UPDATE etl.run_log SET status='FAILED', finished_at=now(), message=%s WHERE run_id=%s",
                        (repr(exc)[:2000], run_id))
        conn.commit()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(run())
