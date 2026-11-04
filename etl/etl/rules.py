"""Business rules, catalogs and normalization functions (pure functions, no I/O)."""
from __future__ import annotations

import hashlib
import re
import unicodedata

import pandas as pd

# ---------------------------------------------------------------------------
# Source column mapping: Excel header -> staging column
# ---------------------------------------------------------------------------
SOURCE_COLUMNS = {
    "Fecha": "fecha", "Mes": "mes", "Año": "anio", "Maquina": "maquina", "Operario": "operario",
    "Referencia": "referencia", "Unidades producidas cada minuto": "unidades_por_minuto",
    "Unidad por display": "unidad_por_display", "Display por paca": "display_por_paca",
    "Pacas producidas": "pacas_producidas", "Horas trabajadas": "horas_trabajadas", "Turno": "turno",
    "Horas no trabajadas": "horas_no_trabajadas", "Tipo de paro": "tipo_de_paro",
    "Observaciones de paro": "observaciones_de_paro",
    "Codigo de paro 1": "cod01_min", "Sub Codigo de paro 1": "subcod01", "Codigo 1 en horas": "cod01_h",
    "Codigo de paro 3": "cod03_min", "Subcodigo 3": "subcod03", "Codigo 3 en horas": "cod03_h",
    "Codigo de paro 5": "cod05_min", "Subcodigo 5": "subcod05", "Codigo 5 en horas": "cod05_h",
    "Área involucrada en subcodigo 5": "area_involucrada_cod05",
    "Personal involucrado": "personal_involucrado",
    "Tiempo de Paro": "tiempo_de_paro", "Observaciones": "observaciones",
}
for _i in (2, 4, *range(6, 19)):
    SOURCE_COLUMNS[f"Codigo de paro {_i}"] = f"cod{_i:02d}_min"
    SOURCE_COLUMNS[f"Codigo {_i} en horas"] = f"cod{_i:02d}_h"

CODE_HOURS = {c: f"cod{c:02d}_h" for c in range(1, 19)}
SUBCODE_COL = {1: "subcod01", 3: "subcod03", 5: "subcod05"}

# ---------------------------------------------------------------------------
# OEE classification of the 18 stoppage codes
#   Planificado   : planned downtime, outside Planned Production Time
#   Calidad       : time lost to quality problems (proxy for the Q factor)
#   Disponibilidad: unplanned downtime (availability loss)
# ---------------------------------------------------------------------------
PLANNED_CODES = {8, 15, 16, 17, 18}
QUALITY_CODES = {11, 12}


def clase_oee(code: int) -> str:
    if code in PLANNED_CODES:
        return "Planificado"
    if code in QUALITY_CODES:
        return "Calidad"
    return "Disponibilidad"


# ---------------------------------------------------------------------------
# Shifts
# ---------------------------------------------------------------------------
TURNOS = [
    # sk, nk, start, end, hours, scheme, night
    (-1, "No registrado", None, None, None, "N/A", False),
    (0, "No aplica", None, None, None, "N/A", False),
    (1, "6am-2pm (Turno 1)", "06:00", "14:00", 8.0, "3x8", False),
    (2, "2pm-10pm (Turno 2)", "14:00", "22:00", 8.0, "3x8", False),
    (3, "10pm-6am (Turno 3)", "22:00", "06:00", 8.0, "3x8", True),
    (4, "6am-6pm", "06:00", "18:00", 12.0, "2x12", False),
    (5, "6pm-6am", "18:00", "06:00", 12.0, "2x12", True),
    (6, "6am-4:30pm", "06:00", "16:30", 10.5, "1x10.5", False),
]
TURNO_ALIASES = {"10pm-6am": "10pm-6am (Turno 3)", "6am-2pm": "6am-2pm (Turno 1)", "2pm-10pm": "2pm-10pm (Turno 2)"}
TURNO_SK = {nk: sk for sk, nk, *_ in TURNOS}


def norm_turno(value) -> str | None:
    if value is None or pd.isna(value):
        return None
    v = " ".join(str(value).split())
    return TURNO_ALIASES.get(v, v)


# ---------------------------------------------------------------------------
# Shift status ("Tipo de paro"): two coding schemes -> one unified status
# ---------------------------------------------------------------------------
ESTADOS = [
    # sk, nk, category, unified code
    (-1, "No registrado", "No registrado", None),
    (1, "Sin novedad", "Turno trabajado", "[19]"),
    (2, "Paro de máquina por ventas", "No programado (comercial)", "[18]"),
    (3, "Falta de programación", "No programado (comercial)", None),
    (4, "Paro por proceso anterior", "Turno perdido (planta)", None),
    (5, "Materia prima no conforme", "Turno perdido (planta)", "[12]"),
    (6, "Falta de materia prima", "Turno perdido (planta)", "[14]"),
    (7, "Espera aval de laboratorio", "Turno perdido (planta)", "[13]"),
    (8, "Falta de operario", "Turno perdido (planta)", "[09]"),
    (9, "Ajuste operativo", "Turno perdido (planta)", "[05]"),
    (10, "Alistamiento / cambio de referencia", "Turno perdido (planta)", "[07]"),
    (11, "Novedad sistemas de potencia", "Turno perdido (planta)", "[03]"),
    (12, "Limpieza no programada", "Turno perdido (planta)", "[06]"),
]
# (regex on the accent-free, upper-case text) -> (estado_nk, scheme)
ESTADO_PATTERNS = [
    (r"^\[19\]", "Sin novedad", "nuevo"),
    (r"^\[18\]", "Paro de máquina por ventas", "nuevo"),
    (r"^17\.\s*PARO DE MAQUINA", "Paro de máquina por ventas", "antiguo"),
    (r"^9\.\s*FALTA DE PROGRAMACION", "Falta de programación", "antiguo"),
    (r"^16\.\s*PARO POR PROCESO ANTERIOR", "Paro por proceso anterior", "antiguo"),
    (r"^10\.\s*PARO POR MATERIA PRIMA", "Materia prima no conforme", "antiguo"),
    (r"^\[12\]", "Materia prima no conforme", "nuevo"),
    (r"^6\.\s*FALTA DE MATERIALES", "Falta de materia prima", "antiguo"),
    (r"^\[14\]", "Falta de materia prima", "nuevo"),
    (r"^15\.\s*APROBACION DE LABORATORIO", "Espera aval de laboratorio", "antiguo"),
    (r"^\[13\]", "Espera aval de laboratorio", "nuevo"),
    (r"^\[09\]", "Falta de operario", "nuevo"),
    (r"^\[05\]", "Ajuste operativo", "nuevo"),
    (r"^4\.\s*AJUSTE DE OPERACION", "Ajuste operativo", "antiguo"),
    (r"^\[07\]", "Alistamiento / cambio de referencia", "nuevo"),
    (r"^5\.\s*AISLAMIENTO", "Alistamiento / cambio de referencia", "antiguo"),
    (r"^\[03\]", "Novedad sistemas de potencia", "nuevo"),
    (r"^3\.\s*AJUSTE ELECTRICO", "Novedad sistemas de potencia", "antiguo"),
    (r"^11\.\s*LIMPIEZA NO PROGRAMADA", "Limpieza no programada", "antiguo"),
]
ESTADO_SK = {nk: sk for sk, nk, *_ in ESTADOS}


def strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")


def map_estado(value) -> tuple[str, str | None]:
    """Return (estado_nk, scheme) for a raw 'Tipo de paro' value."""
    if value is None or pd.isna(value) or not str(value).strip():
        return "No registrado", None
    key = strip_accents(" ".join(str(value).split())).upper()
    for pattern, nk, scheme in ESTADO_PATTERNS:
        if re.search(pattern, key):
            return nk, scheme
    return "No registrado", "desconocido"


# ---------------------------------------------------------------------------
# References (SKU)
# ---------------------------------------------------------------------------
REF_TYPOS = {"Alocdor": "Alocolor", "Stilo Kids": "Estilo Kids"}
REF_NOT_APPLICABLE = {"No aplica"}


def norm_referencia(value) -> str | None:
    if value is None or pd.isna(value) or not str(value).strip():
        return None
    s = " ".join(str(value).split())
    for wrong, right in REF_TYPOS.items():
        s = re.sub(rf"^{re.escape(wrong)}\b", right, s)
    s = re.sub(r"(\d+)\s*cc\b", r"\1cc", s, flags=re.IGNORECASE)
    s = re.sub(r"\(\s*(\d+)\s*col\s*\)", r"(\1 col)", s, flags=re.IGNORECASE)
    return s


def parse_referencia(nk: str) -> dict:
    """Derive brand / presentation (cc) / number of colors from the SKU name."""
    cc = re.search(r"(\d+)cc\b", nk)
    colors = re.search(r"\((\d+) col\)", nk)
    if nk.startswith("Vinilos x"):
        marca = "Vinilos granel"
    else:
        marca = re.split(r"\s+\d", nk, maxsplit=1)[0].strip()
    return {
        "marca": marca,
        "presentacion_cc": int(cc.group(1)) if cc else None,
        "presentacion": f"{cc.group(1)}cc" if cc else "Sin dato",
        "num_colores": int(colors.group(1)) if colors else None,
    }


# ---------------------------------------------------------------------------
# Subcodes ("1.2D  RETENEDORES Y ORING " / "1.2.C Cambio de Valvula" -> 1.2.D / 1.2.C)
# ---------------------------------------------------------------------------
_SUBCODE_RE = re.compile(r"^\s*(\d{1,2})\.(\d{1,2})(?:\s*\.?\s*([A-Za-z])(?=[\s.]|$))?")


# Legacy numbering: in the old scheme "Ajuste operativo" was code 4, so its
# subcodes were typed as 4.x. They are renumbered to the current 5.x catalog
# by matching the subsystem name (5.4 "Banda de salida" did not exist before).
LEGACY_SUBCODES = {5: {"4.1": "5.1", "4.2": "5.2", "4.3": "5.3", "4.4": "5.5",
                       "4.5": "5.6", "4.6": "5.7", "4.7": "5.8", "4.8": "5.9"}}


def norm_subcode_key(value) -> str | None:
    if value is None or pd.isna(value) or not str(value).strip():
        return None
    m = _SUBCODE_RE.match(str(value))
    if not m:
        return None
    key = f"{int(m.group(1))}.{int(m.group(2))}"
    if m.group(3):
        key += f".{m.group(3).upper()}"
    return key


# ---------------------------------------------------------------------------
# People: pseudonymization (Ley 1581 de 2012)
# ---------------------------------------------------------------------------
PERSON_PLACEHOLDERS = {"NO", "NO APLICA", "N/A", "NA", ""}


def norm_persona(value) -> str | None:
    """Normalized name, or None if missing, or 'N/A' for placeholders."""
    if value is None or pd.isna(value):
        return None
    s = " ".join(str(value).split())
    if strip_accents(s).upper() in PERSON_PLACEHOLDERS:
        return "N/A"
    return s


def seudonimo(name: str, salt: str) -> str:
    """Stable, non-reversible pseudonym: PER-<6 hex of salted SHA-256>."""
    if name == "N/A":
        return "N/A"
    digest = hashlib.sha256(f"{salt}|{strip_accents(name).upper()}".encode("utf-8")).hexdigest()
    return f"PER-{digest[:6]}"
