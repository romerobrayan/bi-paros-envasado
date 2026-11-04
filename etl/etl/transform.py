"""Extract -> clean -> transform. Every cleaning rule logs rows before/affected/after."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import rules as R
from .excel_reader import ExcelTables

OUTLIER_FACTOR = 1.5          # bales above 1.5x the ideal output of the shift = outlier
DEFAULT_REF_FOR_MAX_RATE = None


@dataclass
class DQLog:
    entries: list[dict] = field(default_factory=list)

    def add(self, rule_id: str, dq_ref: str, regla: str, accion: str,
            antes: int | None, afectadas: int, despues: int | None) -> None:
        self.entries.append(dict(rule_id=rule_id, dq_ref=dq_ref, regla=regla, accion=accion,
                                 filas_antes=antes, filas_afectadas=int(afectadas), filas_despues=despues))
        print(f"  [{rule_id}] {regla}: affected={afectadas} ({antes} -> {despues})")


# ---------------------------------------------------------------------------
# EXTRACT
# ---------------------------------------------------------------------------
def extract(path: str) -> dict[str, pd.DataFrame]:
    xt = ExcelTables(path)
    try:
        base = xt.read("T_baseDeDatos")
        base = base.rename(columns=R.SOURCE_COLUMNS)
        missing = set(R.SOURCE_COLUMNS.values()) - set(base.columns)
        if missing:
            raise ValueError(f"Source is missing expected columns: {sorted(missing)}")
        base = base[["source_row", *R.SOURCE_COLUMNS.values()]]

        codigos = xt.read("Tabla2")
        sub01 = xt.read("Sin_programación")
        sub03 = xt.read("Tabla9")
        sub05 = xt.read("Tabla10")
        refs = pd.concat([xt.read(t) for t in ("Tabla8", "Tabla14", "Tabla15", "Tabla16")], ignore_index=True)
    finally:
        xt.close()
    return {"base": base, "codigos": codigos, "sub01": sub01, "sub03": sub03, "sub05": sub05, "refs": refs}


# ---------------------------------------------------------------------------
# CATALOGS
# ---------------------------------------------------------------------------
def build_catalogs(raw: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    cod = raw["codigos"].iloc[:, 1:4].copy()
    cod.columns = ["area_impacto", "paro", "clave"]
    cod = cod.dropna(subset=["paro"])
    cod["codigo"] = cod["paro"].str.extract(r"\[(\d+)\]")[0].astype(int)
    cod["descripcion"] = cod["paro"].str.replace(r"^\[\d+\]\s*", "", regex=True).str.strip()

    subs = []
    for code, key in ((1, "sub01"), (3, "sub03"), (5, "sub05")):
        s = raw[key].iloc[:, 1:3].copy()
        s.columns = ["clave", "descripcion"]
        s = s.dropna(subset=["clave"])
        s["clave"] = s["clave"].astype(str).str.strip()
        s["descripcion"] = (s["descripcion"].astype(str).str.replace(r"^\s*\d+\.\d+(\.\w)?\s*", "", regex=True)
                            .str.split().str.join(" "))
        s["codigo"] = code
        subs.append(s)
    sub = pd.concat(subs, ignore_index=True)

    refs = raw["refs"].iloc[:, 1:].copy()
    refs.columns = [" ".join(str(c).split()).lower() for c in refs.columns]
    refs = refs.rename(columns={"maquina": "maquina", "nombre de referencia": "referencia",
                                "# colores": "num_colores", "display": "display_por_paca",
                                "unidades * paca": "unidades_por_paca", "unidades *minuto": "unidades_por_minuto"})
    refs = refs[["maquina", "referencia", "num_colores", "display_por_paca", "unidades_por_paca", "unidades_por_minuto"]]
    refs = refs.dropna(subset=["referencia"])
    refs["maquina"] = refs["maquina"].astype(str).str.strip()
    refs["referencia_norm"] = refs["referencia"].map(R.norm_referencia)
    for c in ("num_colores", "display_por_paca", "unidades_por_paca", "unidades_por_minuto"):
        refs[c] = pd.to_numeric(refs[c], errors="coerce")
    refs = refs.drop_duplicates(subset=["maquina", "referencia"])
    return {"codigos": cod, "subcodigos": sub, "refs": refs}


# ---------------------------------------------------------------------------
# PSEUDONYMIZATION (before anything is written to the database)
# ---------------------------------------------------------------------------
def pseudonymize(base: pd.DataFrame, salt: str, dq: DQLog) -> tuple[pd.DataFrame, pd.DataFrame]:
    if not salt:
        raise RuntimeError("PSEUDONYM_SALT is empty: refusing to process personal data without it")
    df = base.copy()
    people = []
    affected = 0
    for col, role in (("operario", "Operaria/o"), ("personal_involucrado", "Persona involucrada")):
        names = df[col].map(R.norm_persona)
        affected += int(names.notna().sum() - names.eq("N/A").sum())
        df[col] = names.map(lambda n: None if n is None or pd.isna(n) else R.seudonimo(n, salt))
        people.append(pd.DataFrame({"seudonimo": df[col], "rol": role, "area": df["area_involucrada_cod05"]
                                    if col == "personal_involucrado" else None}))
    dq.add("R01", "DQ14", "Seudonimización de nombres de personas",
           "Nombre -> PER-xxxxxx con SHA-256 + salt (.env); los nombres reales no llegan a la BD",
           len(df), affected, len(df))
    return df, pd.concat(people, ignore_index=True).dropna(subset=["seudonimo"])


# ---------------------------------------------------------------------------
# CLEAN
# ---------------------------------------------------------------------------
NUMERIC = ["pacas_producidas", "horas_trabajadas", "horas_no_trabajadas", "tiempo_de_paro",
           *R.CODE_HOURS.values()]


def clean(df: pd.DataFrame, cat: dict[str, pd.DataFrame], dq: DQLog) -> pd.DataFrame:
    df = df.copy()

    # R02 numeric coercion ------------------------------------------------
    n = len(df)
    bad = 0
    for c in NUMERIC:
        conv = pd.to_numeric(df[c], errors="coerce")
        bad += int((df[c].notna() & conv.isna()).sum())
        df[c] = conv
    df["fecha"] = pd.to_datetime(df["fecha"], errors="coerce")
    bad_dates = int(df["fecha"].isna().sum())
    dq.add("R02", "-", "Conversión de tipos numéricos y fecha",
           "Texto no numérico -> NULL; fechas inválidas descartadas", n, bad + bad_dates, n - bad_dates)
    df = df[df["fecha"].notna()]

    # R03 exact duplicates --------------------------------------------------
    n = len(df)
    payload = [c for c in df.columns if c != "source_row"]
    dup = df.duplicated(subset=payload, keep="first")
    df = df[~dup]
    dq.add("R03", "DQ8", "Duplicados exactos", "Se conserva la primera ocurrencia", n, int(dup.sum()), len(df))

    # R04 empty columns -----------------------------------------------------
    empty_cols = [c for c in ("unidades_por_minuto", "display_por_paca") if df[c].isna().all()]
    df = df.drop(columns=empty_cols)
    dq.add("R04", "DQ10", "Columnas 100% vacías", f"Eliminadas: {', '.join(empty_cols)} (el dato sale del catálogo)",
           len(df), 0, len(df))

    # R05 shift: redundant column + aliases -----------------------------------
    n = len(df)
    df["turno"] = df["turno"].map(R.norm_turno)
    df["unidad_por_display"] = df["unidad_por_display"].map(R.norm_turno)
    redundant = df["unidad_por_display"].notna()
    fill = df["turno"].isna() & redundant
    df.loc[fill, "turno"] = df.loc[fill, "unidad_por_display"]
    dq.add("R05", "DQ2", "Turno digitado en la columna 'Unidad por display'",
           f"Columna redundante ({int(redundant.sum())} filas con el turno repetido); se usa como respaldo "
           f"({int(fill.sum())} turnos recuperados) y se elimina", n, int(redundant.sum()), n)
    df = df.drop(columns=["unidad_por_display"])

    # R06 missing shift -----------------------------------------------------
    miss = df["turno"].isna()
    unknown = df["turno"].notna() & ~df["turno"].isin(R.TURNO_SK)
    df.loc[miss | unknown, "turno"] = "No registrado"
    dq.add("R06", "DQ1", "Turno vacío o fuera de catálogo", "Asignado al miembro 'No registrado' (SK -1)",
           n, int(miss.sum() + unknown.sum()), n)

    # R07 shift status: unify the two coding schemes -------------------------
    mapped = df["tipo_de_paro"].map(R.map_estado)
    df["estado_nk"] = mapped.str[0]
    scheme = mapped.str[1]
    dq.add("R07", "DQ3", "Tipo de paro con dos esquemas de codificación",
           f"Mapeo a estado unificado: {int((scheme == 'antiguo').sum())} del esquema antiguo, "
           f"{int((scheme == 'nuevo').sum())} del nuevo, {int((scheme == 'desconocido').sum())} sin mapeo",
           n, int((scheme == "antiguo").sum()), n)

    # R08 references --------------------------------------------------------
    raw_ref = df["referencia"].copy()
    df["referencia"] = df["referencia"].map(R.norm_referencia)
    changed = raw_ref.notna() & (raw_ref.astype(str) != df["referencia"].astype(str))
    dq.add("R08", "DQ7", "Normalización de referencias (typos, espacios, '(12col)')",
           f"{raw_ref.nunique()} valores distintos -> {df['referencia'].nunique()}", n, int(changed.sum()), n)
    missing_ref = df["referencia"].isna()
    df.loc[missing_ref, "referencia"] = "No registrada"
    dq.add("R09", "DQ12", "Referencia vacía (todo 2022 y parte de 2023)",
           "Miembro 'No registrada' (SK -1); el Rendimiento no es calculable en esas filas",
           n, int(missing_ref.sum()), n)

    # R10 people placeholders -------------------------------------------------
    ph = df["operario"].eq("N/A")
    nul = df["operario"].isna()
    df.loc[nul, "operario"] = "No registrado"
    dq.add("R10", "DQ11", "Operario 'No' / 'No aplica' / vacío",
           f"{int(ph.sum())} -> 'No aplica' (SK 0); {int(nul.sum())} -> 'No registrado' (SK -1)",
           n, int(ph.sum() + nul.sum()), n)

    # R11 record type + empty rows -------------------------------------------
    ht = df["horas_trabajadas"].notna()
    hn = df["horas_no_trabajadas"].notna()
    paro = df["tiempo_de_paro"].fillna(0) > 0
    df["tipo_registro"] = np.select(
        [ht, ~ht & hn, ~ht & ~hn & paro],
        ["PRODUCCION", "NO_PROGRAMADO", "COMPLEMENTO"], default="VACIO")
    vacio = df["tipo_registro"].eq("VACIO")
    counts = df["tipo_registro"].value_counts().to_dict()
    df = df[~vacio]
    dq.add("R11", "DQ5", "Clasificación del tipo de registro",
           f"PRODUCCION={counts.get('PRODUCCION', 0)}, NO_PROGRAMADO={counts.get('NO_PROGRAMADO', 0)}, "
           f"COMPLEMENTO (Ingreso subcódigo)={counts.get('COMPLEMENTO', 0)}; VACIO eliminados={int(vacio.sum())}",
           n, int(vacio.sum()), len(df))
    for c in ("horas_trabajadas", "horas_no_trabajadas", "pacas_producidas", "tiempo_de_paro", *R.CODE_HOURS.values()):
        df[c] = df[c].fillna(0.0)
    return df


# ---------------------------------------------------------------------------
# TRANSFORM: stoppages (unpivot) and shift production
# ---------------------------------------------------------------------------
def build_causas(cat: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows = []
    cod = cat["codigos"].set_index("codigo")
    sub = cat["subcodigos"]
    for code in range(1, 19):
        area = cod.at[code, "area_impacto"] if code in cod.index else "Sin área"
        desc = cod.at[code, "descripcion"] if code in cod.index else f"Código {code}"
        base = dict(area_impacto=area, codigo=code, codigo_txt=f"[{code:02d}]", codigo_descripcion=desc,
                    codigo_label=f"[{code:02d}] {desc}", clase_oee=R.clase_oee(code),
                    es_planificado=R.clase_oee(code) == "Planificado")
        rows.append({**base, "causa_nk": f"{code:02d}", "sistema_clave": None, "sistema": "Sin subcódigo",
                     "componente_clave": None, "componente": "Sin detalle", "nivel_detalle": 1})
        s = sub[sub["codigo"] == code]
        systems = s[~s["clave"].str.contains(r"\.[A-Z]$", regex=True)]
        for _, sy in systems.iterrows():
            sys_label = f"{sy['clave']} {sy['descripcion']}"
            rows.append({**base, "causa_nk": f"{code:02d}|{sy['clave']}", "sistema_clave": sy["clave"],
                         "sistema": sys_label, "componente_clave": None, "componente": "Sin detalle",
                         "nivel_detalle": 2})
            comps = s[s["clave"].str.startswith(sy["clave"] + ".")]
            for _, co in comps.iterrows():
                rows.append({**base, "causa_nk": f"{code:02d}|{co['clave']}", "sistema_clave": sy["clave"],
                             "sistema": sys_label, "componente_clave": co["clave"],
                             "componente": f"{co['clave']} {co['descripcion']}", "nivel_detalle": 3})
    causas = pd.DataFrame(rows)
    causas.insert(0, "causa_sk", range(1, len(causas) + 1))
    return causas


def unpivot_paros(df: pd.DataFrame, causas: pd.DataFrame, dq: DQLog) -> pd.DataFrame:
    nk_to_sk = dict(zip(causas["causa_nk"], causas["causa_sk"]))
    parts = []
    stats = {"exact": 0, "degraded": 0, "no_sub": 0, "unknown": 0, "legacy": 0}
    for code, hcol in R.CODE_HOURS.items():
        sel = df[df[hcol] > 0]
        if sel.empty:
            continue
        p = pd.DataFrame({
            "registro_id": sel["source_row"].values,
            "codigo": code,
            "horas_paro": sel[hcol].values,
        })
        if code in R.SUBCODE_COL:
            keys = sel[R.SUBCODE_COL[code]].map(R.norm_subcode_key).values
            legacy = R.LEGACY_SUBCODES.get(code, {})
            nks = []
            for k in keys:
                if isinstance(k, str) and k in legacy:
                    k = legacy[k]
                    stats["legacy"] += 1
                if k is None or pd.isna(k):
                    nks.append(f"{code:02d}"); stats["no_sub"] += 1
                elif f"{code:02d}|{k}" in nk_to_sk:
                    nks.append(f"{code:02d}|{k}"); stats["exact"] += 1
                elif f"{code:02d}|{'.'.join(k.split('.')[:2])}" in nk_to_sk:
                    nks.append(f"{code:02d}|{'.'.join(k.split('.')[:2])}"); stats["degraded"] += 1
                else:
                    nks.append(f"{code:02d}"); stats["unknown"] += 1
            p["causa_nk"] = nks
        else:
            p["causa_nk"] = f"{code:02d}"
        if code == 5:
            p["agente_involucrado"] = sel["area_involucrada_cod05"].values
            p["persona_involucrada"] = sel["personal_involucrado"].values
        else:
            p["agente_involucrado"] = None
            p["persona_involucrada"] = "N/A"   # role does not apply outside code 05 -> SK 0
        parts.append(p)
    paros = pd.concat(parts, ignore_index=True)
    paros["causa_sk"] = paros["causa_nk"].map(nk_to_sk)
    paros["minutos_paro"] = (paros["horas_paro"] * 60).round(2)
    paros["evento_falla"] = (paros["codigo"] == 1).astype(int)
    total_sub = stats["exact"] + stats["degraded"] + stats["no_sub"] + stats["unknown"]
    dq.add("R12", "DQ4", "Normalización de subcódigos de los códigos 01, 03 y 05",
           f"renumerados del esquema antiguo 4.x -> 5.x={stats['legacy']}; exactos={stats['exact']}, degradados a nivel sistema={stats['degraded']}, "
           f"sin subcódigo={stats['no_sub']}, no reconocidos -> nivel código={stats['unknown']}",
           total_sub, stats["legacy"] + stats["degraded"] + stats["unknown"], total_sub)
    dq.add("R13", "-", "Unpivot de 18 pares de columnas de código a filas",
           f"{len(df)} registros -> {len(paros)} filas de paro (solo duraciones > 0)", len(df), len(paros), len(paros))
    return paros


def link_complements(df: pd.DataFrame, dq: DQLog) -> pd.Series:
    """Map each COMPLEMENTO row to the PRODUCCION row of the same form (parent)."""
    prod = df[df["tipo_registro"] == "PRODUCCION"]
    comp = df[df["tipo_registro"] == "COMPLEMENTO"]
    strict = ["fecha", "maquina", "turno", "operario", "referencia"]
    relaxed = ["fecha", "maquina", "operario"]
    parent = pd.Series(pd.NA, index=comp.index, dtype="Int64")
    first_strict = prod.groupby(strict)["source_row"].first()
    first_relaxed = prod.groupby(relaxed)["source_row"].first()
    k1 = pd.MultiIndex.from_frame(comp[strict])
    parent[:] = first_strict.reindex(k1).values
    m1 = int(parent.notna().sum())
    rest = parent.isna()
    k2 = pd.MultiIndex.from_frame(comp.loc[rest, relaxed])
    parent.loc[rest] = first_relaxed.reindex(k2).values
    m2 = int(parent.notna().sum()) - m1
    dq.add("R14", "DQ5", "Vincular registros complemento (Ingreso subcódigo) con su formulario padre",
           f"llave estricta={m1}, llave relajada (fecha+máquina+operario)={m2}, "
           f"sin padre={int(parent.isna().sum())} (sus paros quedan solo en fact_paro)",
           len(comp), m1 + m2, len(comp))
    return parent


def build_produccion(df: pd.DataFrame, paros: pd.DataFrame, parent: pd.Series, refs: pd.DataFrame,
                     maquina_upm: dict[str, float], dq: DQLog) -> pd.DataFrame:
    base = df[df["tipo_registro"].isin(["PRODUCCION", "NO_PROGRAMADO"])].copy()

    # parent id per stoppage row (production rows are their own parent)
    parent_map = pd.Series(parent.values, index=df.loc[parent.index, "source_row"].values)
    own = base["source_row"]
    paros["registro_padre_id"] = paros["registro_id"].map(parent_map)
    is_own = paros["registro_id"].isin(own)
    paros.loc[is_own, "registro_padre_id"] = paros.loc[is_own, "registro_id"]

    by_parent = (paros.dropna(subset=["registro_padre_id"])
                 .assign(clase=lambda x: x["codigo"].map(R.clase_oee))
                 .pivot_table(index="registro_padre_id", columns="clase", values="horas_paro",
                              aggfunc="sum", fill_value=0.0))
    for c in ("Planificado", "Disponibilidad", "Calidad"):
        if c not in by_parent:
            by_parent[c] = 0.0
    by_parent.index = by_parent.index.astype("int64")
    base = base.join(by_parent, on="source_row")
    base[["Planificado", "Disponibilidad", "Calidad"]] = base[["Planificado", "Disponibilidad", "Calidad"]].fillna(0.0)
    n_comp = parent.dropna().astype("int64").value_counts()
    base["n_complementos"] = base["source_row"].map(n_comp).fillna(0).astype(int)

    base["horas_paro_planificado"] = base["Planificado"]
    base["horas_paro_disponibilidad"] = base["Disponibilidad"]
    base["horas_paro_calidad"] = base["Calidad"]
    total_paro = base["Planificado"] + base["Disponibilidad"] + base["Calidad"]

    h = base["horas_trabajadas"]
    base["horas_planificadas"] = (h - base["Planificado"]).clip(lower=0)
    base["horas_operativas"] = (base["horas_planificadas"] - base["Disponibilidad"]).clip(lower=0)
    base["paro_excede_turno"] = (base["tipo_registro"] == "PRODUCCION") & (total_paro > h + 1e-9)
    dq.add("R15", "DQ9", "Tiempo de paro mayor que las horas trabajadas",
           "Marcado paro_excede_turno; horas planificadas/operativas acotadas en 0 (el paro se conserva)",
           len(base), int(base["paro_excede_turno"].sum()), len(base))

    # ideal rate (bales/hour) = machine speed (units/min) x 60 / units per bale (machine x reference)
    rate_tbl = refs.dropna(subset=["unidades_por_paca"])
    rate_tbl = rate_tbl[rate_tbl["unidades_por_paca"] > 0]
    upaca_mr = rate_tbl.groupby(["maquina", "referencia_norm"])["unidades_por_paca"].first()
    upaca_r = rate_tbl.groupby("referencia_norm")["unidades_por_paca"].agg(lambda s: s.mode().iloc[0])
    key = pd.MultiIndex.from_frame(base[["maquina", "referencia"]])
    upaca = pd.Series(upaca_mr.reindex(key).values, index=base.index)
    fallback = upaca.isna() & base["referencia"].isin(upaca_r.index)
    upaca[fallback] = base.loc[fallback, "referencia"].map(upaca_r)
    upm = base["maquina"].map(maquina_upm)
    base["pacas_hora_ideal"] = (upm * 60 / upaca).where(upaca > 0)
    base["pacas_ideales"] = (base["horas_operativas"] * base["pacas_hora_ideal"]).round(2)
    prod = base["tipo_registro"] == "PRODUCCION"
    no_rate = prod & base["pacas_hora_ideal"].isna() & (base["horas_trabajadas"] > 0)
    dq.add("R16", "DQ12", "Tasa ideal no calculable (referencia vacía o fuera del catálogo)",
           f"{int(fallback.sum())} filas usaron la unidades/paca de otra máquina; "
           f"{int(no_rate.sum())} filas quedan fuera del Rendimiento", int(prod.sum()), int(no_rate.sum()), int(prod.sum()))

    # outliers: more than 1.5x the ideal output of the whole shift. If the rate is
    # unknown, compare with the fastest reference of that machine.
    max_rate = (rate_tbl.assign(r=lambda x: x["maquina"].map(maquina_upm) * 60 / x["unidades_por_paca"])
                .groupby("maquina")["r"].max())
    ref_rate = base["pacas_hora_ideal"].fillna(base["maquina"].map(max_rate))
    cap = OUTLIER_FACTOR * base["horas_trabajadas"] * ref_rate
    base["es_atipico"] = prod & (base["pacas_producidas"] > cap) & cap.notna()
    dq.add("R17", "DQ6", f"Producción atípica (> {OUTLIER_FACTOR}x la producción ideal del turno)",
           "Marcado es_atipico; se EXCLUYE solo del Rendimiento, se conserva en el total de pacas",
           int(prod.sum()), int(base["es_atipico"].sum()), int(prod.sum()))

    base["incluir_en_rendimiento"] = (prod & base["pacas_hora_ideal"].notna() & ~base["es_atipico"]
                                      & (base["horas_operativas"] > 0))
    base["horas_no_programadas"] = base["horas_no_trabajadas"]
    return base
