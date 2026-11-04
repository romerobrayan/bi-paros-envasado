"""Build dimensions, resolve surrogate keys and load PostgreSQL (full refresh)."""
from __future__ import annotations

import io

import pandas as pd
import psycopg2

from . import rules as R

DW_TABLES_TRUNCATE = [
    "dw.fact_produccion_hora", "dw.fact_paro", "dw.fact_produccion_turno",
    "dw.dim_causa_paro", "dw.dim_persona", "dw.dim_referencia", "dw.dim_maquina",
    "dw.dim_turno", "dw.dim_estado_turno",
    "stg.base_datos_raw", "stg.cat_codigos", "stg.cat_subcodigos", "stg.cat_referencias",
]


def copy_df(cur, df: pd.DataFrame, table: str) -> int:
    """Fast bulk insert with COPY ... FROM STDIN (CSV)."""
    buf = io.StringIO()
    df.to_csv(buf, index=False, header=False, na_rep="\\N")
    buf.seek(0)
    cols = ",".join(df.columns)
    cur.copy_expert(f"COPY {table} ({cols}) FROM STDIN WITH (FORMAT csv, NULL '\\N')", buf)
    return len(df)


# ---------------------------------------------------------------------------
# Dimensions
# ---------------------------------------------------------------------------
def dim_turno() -> pd.DataFrame:
    return pd.DataFrame(R.TURNOS, columns=["turno_sk", "turno_nk", "hora_inicio", "hora_fin",
                                           "duracion_h", "esquema", "es_nocturno"])


def dim_estado() -> pd.DataFrame:
    return pd.DataFrame(R.ESTADOS, columns=["estado_sk", "estado_nk", "categoria", "codigo_unificado"])


def dim_maquina(refs: pd.DataFrame, since: str) -> pd.DataFrame:
    upm = (refs[refs["unidades_por_minuto"] > 0].groupby("maquina")["unidades_por_minuto"]
           .agg(lambda s: s.mode().iloc[0]))
    return pd.DataFrame({
        "maquina_sk": range(1, len(upm) + 1),
        "maquina_nk": upm.index, "velocidad_ideal_upm": upm.values, "vigente_desde": since,
        "motivo_version": "Versión inicial (catálogo Tablas Desplegables)",
    })


def dim_referencia(df: pd.DataFrame, refs: pd.DataFrame) -> pd.DataFrame:
    in_cat = set(refs["referencia_norm"])
    upaca = (refs[refs["unidades_por_paca"] > 0].groupby("referencia_norm")["unidades_por_paca"]
             .agg(lambda s: s.mode().iloc[0]))
    colors = refs.groupby("referencia_norm")["num_colores"].max()
    names = sorted((set(df["referencia"]) | in_cat) - {"No registrada", *R.REF_NOT_APPLICABLE})
    rows = [dict(referencia_sk=-1, referencia_nk="No registrada", marca="No registrada", presentacion_cc=None,
                 presentacion="Sin dato", num_colores=None, unidades_por_paca=None, en_catalogo=False),
            dict(referencia_sk=0, referencia_nk="No aplica", marca="No aplica", presentacion_cc=None,
                 presentacion="Sin dato", num_colores=None, unidades_por_paca=None, en_catalogo=False)]
    for i, nk in enumerate(names, start=1):
        p = R.parse_referencia(nk)
        nc = p["num_colores"] if p["num_colores"] is not None else colors.get(nk)
        rows.append(dict(referencia_sk=i, referencia_nk=nk, marca=p["marca"], presentacion_cc=p["presentacion_cc"],
                         presentacion=p["presentacion"], num_colores=None if pd.isna(nc) else int(nc),
                         unidades_por_paca=None if nk not in upaca else int(upaca[nk]), en_catalogo=nk in in_cat))
    out = pd.DataFrame(rows)
    out["presentacion_cc"] = out["presentacion_cc"].astype("Int64")
    out["num_colores"] = out["num_colores"].astype("Int64")
    out["unidades_por_paca"] = out["unidades_por_paca"].astype("Int64")
    return out


def dim_persona(people: pd.DataFrame) -> pd.DataFrame:
    p = people[people["seudonimo"] != "N/A"]
    roles = p.groupby("seudonimo").apply(
        lambda g: _rol(set(g["rol"]), set(g["area"].dropna())), include_groups=False)
    rows = [dict(persona_sk=-1, seudonimo="No registrado", rol_principal="N/A"),
            dict(persona_sk=0, seudonimo="No aplica", rol_principal="N/A")]
    for i, (s, rol) in enumerate(sorted(roles.items()), start=1):
        rows.append(dict(persona_sk=i, seudonimo=s, rol_principal=rol))
    return pd.DataFrame(rows)


def _rol(roles: set, areas: set) -> str:
    if "Operaria/o" in roles:
        return "Mixto" if "Personal_de_mantenimiento" in areas else "Operaria/o"
    if "Personal_de_mantenimiento" in areas:
        return "Mantenimiento"
    return "Operaria/o" if "Operarios" in areas else "Otro"


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------
def persona_sk(series: pd.Series, mapping: dict) -> pd.Series:
    return series.map(lambda v: -1 if v is None or pd.isna(v) or v == "No registrado"
                      else 0 if v == "N/A" else mapping.get(v, -1)).astype(int)


def load_all(conn, raw_stage: pd.DataFrame, cat: dict, clean_df: pd.DataFrame, causas: pd.DataFrame,
             paros: pd.DataFrame, prod: pd.DataFrame, people: pd.DataFrame, calendar: tuple[str, str]) -> dict:
    counts = {}
    with conn.cursor() as cur:
        cur.execute("TRUNCATE " + ", ".join(DW_TABLES_TRUNCATE) + " CASCADE")
        cur.execute("CALL etl.sp_cargar_dim_fecha(%s, %s)", calendar)

        # staging --------------------------------------------------------------
        counts["stg.base_datos_raw"] = copy_df(cur, raw_stage.astype("string"), "stg.base_datos_raw")
        c = cat["codigos"][["codigo", "paro", "area_impacto", "clave"]]
        counts["stg.cat_codigos"] = copy_df(cur, c, "stg.cat_codigos")
        counts["stg.cat_subcodigos"] = copy_df(cur, cat["subcodigos"][["codigo", "clave", "descripcion"]]
                                               .drop_duplicates(["codigo", "clave"]), "stg.cat_subcodigos")
        r = cat["refs"].copy()
        for col in ("num_colores", "display_por_paca", "unidades_por_paca", "unidades_por_minuto"):
            r[col] = r[col].astype("Int64")
        counts["stg.cat_referencias"] = copy_df(cur, r[["maquina", "referencia", "referencia_norm", "num_colores",
                                                        "display_por_paca", "unidades_por_paca",
                                                        "unidades_por_minuto"]], "stg.cat_referencias")

        # dimensions -----------------------------------------------------------
        counts["dw.dim_turno"] = copy_df(cur, dim_turno(), "dw.dim_turno")
        counts["dw.dim_estado_turno"] = copy_df(cur, dim_estado(), "dw.dim_estado_turno")
        dm = dim_maquina(cat["refs"], calendar[0])
        counts["dw.dim_maquina"] = copy_df(cur, dm, "dw.dim_maquina")
        # keep the serial in sync so SCD2 inserts (new versions) get the next SK
        cur.execute("SELECT setval(pg_get_serial_sequence('dw.dim_maquina','maquina_sk'), "
                    "(SELECT MAX(maquina_sk) FROM dw.dim_maquina))")
        dr = dim_referencia(clean_df, cat["refs"])
        counts["dw.dim_referencia"] = copy_df(cur, dr, "dw.dim_referencia")
        dp = dim_persona(people)
        counts["dw.dim_persona"] = copy_df(cur, dp, "dw.dim_persona")
        counts["dw.dim_causa_paro"] = copy_df(cur, causas[[
            "causa_sk", "causa_nk", "area_impacto", "codigo", "codigo_txt", "codigo_descripcion", "codigo_label",
            "sistema_clave", "sistema", "componente_clave", "componente", "nivel_detalle", "clase_oee",
            "es_planificado"]], "dw.dim_causa_paro")

        # surrogate key lookups (SCD2: version valid at the fact date) -------------
        cur.execute("SELECT maquina_nk, maquina_sk, vigente_desde, vigente_hasta FROM dw.dim_maquina")
        versions = pd.DataFrame(cur.fetchall(), columns=["maquina", "maquina_sk", "desde", "hasta"])
        ref_sk = dict(zip(dr["referencia_nk"], dr["referencia_sk"]))
        per_sk = dict(zip(dp["seudonimo"], dp["persona_sk"]))

        def keys(frame: pd.DataFrame) -> pd.DataFrame:
            out = frame.copy()
            out["fecha_sk"] = out["fecha"].dt.strftime("%Y%m%d").astype(int)
            out["turno_sk"] = out["turno"].map(R.TURNO_SK).fillna(-1).astype(int)
            m = out[["maquina", "fecha"]].rename_axis("_ix").reset_index().merge(versions, on="maquina", how="left")
            m = m[(m["fecha"].dt.date >= m["desde"]) & (m["fecha"].dt.date < m["hasta"])].set_index("_ix")
            out["maquina_sk"] = m["maquina_sk"].reindex(out.index)
            if out["maquina_sk"].isna().any():
                raise ValueError("Rows without a valid machine version (SCD2 lookup failed)")
            out["maquina_sk"] = out["maquina_sk"].astype(int)
            out["referencia_sk"] = out["referencia"].map(
                lambda v: -1 if v == "No registrada" else 0 if v in R.REF_NOT_APPLICABLE else ref_sk.get(v, -1))
            out["operario_sk"] = persona_sk(out["operario"], per_sk)
            return out

        # fact_produccion_turno ------------------------------------------------
        p = keys(prod)
        p["estado_sk"] = p["estado_nk"].map(R.ESTADO_SK).fillna(-1).astype(int)
        fpt = p.rename(columns={"source_row": "registro_id"})[[
            "registro_id", "fecha_sk", "turno_sk", "maquina_sk", "referencia_sk", "operario_sk", "estado_sk",
            "tipo_registro", "horas_trabajadas", "horas_no_programadas", "horas_paro_planificado",
            "horas_paro_disponibilidad", "horas_paro_calidad", "horas_planificadas", "horas_operativas",
            "pacas_producidas", "pacas_hora_ideal", "pacas_ideales", "n_complementos", "es_atipico",
            "paro_excede_turno", "incluir_en_rendimiento"]].round(5)
        counts["dw.fact_produccion_turno"] = copy_df(cur, fpt, "dw.fact_produccion_turno")

        # fact_paro --------------------------------------------------------------
        ctx = keys(clean_df.set_index("source_row", drop=False))
        ctx = ctx[["fecha_sk", "turno_sk", "maquina_sk", "referencia_sk", "operario_sk"]]
        fp = paros.join(ctx, on="registro_id")
        fp["persona_involucrada_sk"] = persona_sk(fp["persona_involucrada"], per_sk)
        fp["registro_padre_id"] = fp["registro_padre_id"].astype("Int64")
        fp = fp[["registro_id", "registro_padre_id", "fecha_sk", "turno_sk", "maquina_sk", "referencia_sk",
                 "operario_sk", "persona_involucrada_sk", "causa_sk", "agente_involucrado", "minutos_paro",
                 "horas_paro", "evento_falla"]]
        fp["horas_paro"] = fp["horas_paro"].round(6)
        counts["dw.fact_paro"] = copy_df(cur, fp, "dw.fact_paro")
    return counts


def write_logs(conn, run_id: int, dq_entries: list[dict], recon: list[dict]) -> None:
    with conn.cursor() as cur:
        for e in dq_entries:
            cur.execute("""INSERT INTO etl.dq_log (run_id, rule_id, dq_ref, regla, accion, filas_antes,
                           filas_afectadas, filas_despues) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                        (run_id, e["rule_id"], e["dq_ref"], e["regla"], e["accion"], e["filas_antes"],
                         e["filas_afectadas"], e["filas_despues"]))
        for r in recon:
            cur.execute("""INSERT INTO etl.reconciliacion (run_id, metrica, valor_fuente, valor_cargado, explicacion)
                           VALUES (%s,%s,%s,%s,%s)""",
                        (run_id, r["metrica"], float(r["fuente"]), float(r["cargado"]), r["explicacion"]))


def connect(dsn: str):
    return psycopg2.connect(dsn)
