"""Generates the 4 report pages of the Power BI project in PBIR format.

Run with Power BI Desktop CLOSED, from the repository root:
    python powerbi/build_report_pages.py
then open powerbi/BI_Paros_Envasado.pbip.

Field names are the display names used in the semantic model (columns renamed
in Power BI, e.g. dim_maquina[maquina_nk] -> [Máquina]). This script builds the
first version of the pages; the page navigator (Insertar > Botones > Navegador)
was added afterwards in Power BI Desktop and is not generated here.

The script reuses the $schema versions that Power BI Desktop wrote itself
(existing page.json / visual.json), so the files match the installed version.
"""
import json
import shutil
import uuid
from pathlib import Path

ROOT = Path(__file__).parent / "BI_Paros_Envasado.Report" / "definition"
PAGES = ROOT / "pages"


def find_template_schemas():
    page_schema = visual_schema = None
    for page_json in PAGES.glob("*/page.json"):
        page_schema = json.loads(page_json.read_text(encoding="utf-8"))["$schema"]
        for vj in page_json.parent.glob("visuals/*/visual.json"):
            visual_schema = json.loads(vj.read_text(encoding="utf-8"))["$schema"]
            print("Template visual.json:\n" + vj.read_text(encoding="utf-8"))
            break
    if not visual_schema:
        raise SystemExit("No visual.json template found: create any visual in Power BI, save, and rerun.")
    return page_schema, visual_schema


# ---------------------------------------------------------------------------
# field helpers
# ---------------------------------------------------------------------------
def col(entity, prop):
    return {"field": {"Column": {"Expression": {"SourceRef": {"Entity": entity}}, "Property": prop}},
            "queryRef": f"{entity}.{prop}", "nativeQueryRef": prop, "active": True}


def mea(prop, entity="_Medidas"):
    return {"field": {"Measure": {"Expression": {"SourceRef": {"Entity": entity}}, "Property": prop}},
            "queryRef": f"{entity}.{prop}", "nativeQueryRef": prop}


def lit(text):
    return {"expr": {"Literal": {"Value": "'" + text.replace("'", "''") + "'"}}}


def title_obj(text):
    return {"title": [{"properties": {"show": {"expr": {"Literal": {"Value": "true"}}}, "text": lit(text)}}]}


def visual(vtype, x, y, w, h, roles, title=None, sort=None, objects=None):
    v = {"visualType": vtype, "query": {"queryState": {r: {"projections": p} for r, p in roles.items()}},
         "drillFilterOtherVisuals": True}
    if sort:
        field, direction = sort
        v["query"]["sortDefinition"] = {"sort": [{"field": field["field"], "direction": direction}],
                                        "isDefaultSort": False}
    if objects:
        v["objects"] = objects
    if title:
        v["visualContainerObjects"] = title_obj(title)
    return {"position": {"x": x, "y": y, "z": 0, "width": w, "height": h}, "visual": v}


def slicer(x, y, w, h, field, title):
    return visual("slicer", x, y, w, h, {"Values": [field]}, title,
                  objects={"data": [{"properties": {"mode": lit("Dropdown")}}]})


def common_slicers():
    return [
        slicer(1180, 20, 230, 90, col("dim_fecha", "Año"), "Año"),
        slicer(1425, 20, 230, 90, col("dim_maquina", "Máquina"), "Máquina"),
        slicer(1670, 20, 230, 90, col("dim_turno", "Turno"), "Turno"),
    ]


# ---------------------------------------------------------------------------
# pages
# ---------------------------------------------------------------------------
P1 = [  # Resumen ejecutivo
    visual("card", 20, 130, 360, 150, {"Values": [mea("OEE")]}, "OEE"),
    visual("card", 395, 130, 360, 150, {"Values": [mea("Disponibilidad")]}, "Disponibilidad"),
    visual("card", 770, 130, 360, 150, {"Values": [mea("Rendimiento")]}, "Rendimiento"),
    visual("card", 1145, 130, 360, 150, {"Values": [mea("Calidad")]}, "Calidad (aprox.)"),
    visual("card", 1520, 130, 380, 150, {"Values": [mea("Pacas Producidas")]}, "Pacas producidas"),
    visual("lineChart", 20, 300, 1240, 420,
           {"Category": [col("dim_fecha", "Año-Mes")], "Y": [mea("OEE")], "Series": [col("dim_maquina", "Máquina")]},
           "OEE mensual por máquina"),
    visual("gauge", 1280, 300, 620, 420, {"Y": [mea("OEE")], "TargetValue": [mea("Meta OEE")]},
           "OEE frente a la meta (75%)"),
    visual("clusteredColumnChart", 20, 740, 940, 320,
           {"Category": [col("dim_fecha", "Año")], "Y": [mea("OEE"), mea("OEE Año Anterior")]},
           "OEE vs año anterior"),
    # a tableEx generated this way rendered only the first column, so it is a matrix
    visual("pivotTable", 980, 740, 920, 320,
           {"Rows": [col("dim_maquina", "Máquina")],
            "Values": [mea("OEE"), mea("Var OEE vs Año Anterior (pp)"), mea("TEEP"), mea("Horas Paro")]},
           "Resumen por máquina"),
]

P2 = [  # Análisis de paros
    visual("lineClusteredColumnComboChart", 20, 130, 1180, 460,
           {"Category": [col("dim_causa_paro", "Código")], "Y": [mea("Horas Paro")],
            "Y2": [mea("Pareto % Acumulado"), mea("Línea 80%")]},
           "Pareto de causas de paro", sort=(mea("Horas Paro"), "Descending")),
    visual("pivotTable", 1220, 130, 680, 460,
           {"Rows": [col("dim_causa_paro", "Área"), col("dim_causa_paro", "Código"),
                     col("dim_causa_paro", "Sistema"), col("dim_causa_paro", "Componente")],
            "Values": [mea("Horas Paro"), mea("% Participación Paro"), mea("Eventos de Paro")]},
           "Jerarquía de paros: Área > Código > Sistema > Componente (drill-down)"),
    visual("decompositionTreeVisual", 20, 610, 1180, 450,
           {"Analyze": [mea("Horas Paro")],
            "ExplainBy": [col("dim_causa_paro", "Área"), col("dim_causa_paro", "Código"),
                          col("dim_causa_paro", "Sistema"), col("dim_causa_paro", "Componente"),
                          col("dim_maquina", "Máquina")]},
           "Árbol de descomposición de horas de paro"),
    visual("clusteredColumnChart", 1220, 610, 680, 450,
           {"Category": [col("dim_maquina", "Máquina")], "Y": [mea("% Paro sobre Horas Trabajadas")],
            "Series": [col("dim_causa_paro", "Clase OEE")]},
           "% de paro sobre horas trabajadas (P-MTO-22)"),
]

P3 = [  # Mantenimiento
    visual("card", 20, 130, 600, 150, {"Values": [mea("Fallas")]}, "Fallas (código 01)"),
    visual("card", 650, 130, 600, 150, {"Values": [mea("MTTR (h)")]}, "MTTR (h)"),
    visual("card", 1280, 130, 620, 150, {"Values": [mea("MTBF (h)")]}, "MTBF (h)"),
    # MTBF (~60 h) and MTTR (~0.7 h) need separate axes
    visual("lineClusteredColumnComboChart", 20, 300, 900, 380,
           {"Category": [col("dim_maquina", "Máquina")], "Y": [mea("MTBF (h)")], "Y2": [mea("MTTR (h)")]},
           "MTBF y MTTR por máquina"),
    visual("pivotTable", 940, 300, 960, 380,
           {"Rows": [col("dim_causa_paro", "Sistema"), col("dim_causa_paro", "Componente")],
            "Values": [mea("Fallas"), mea("Horas Falla"), mea("MTTR (h)")]},
           "Fallas por sistema y componente"),
    visual("lineChart", 20, 700, 1880, 360,
           {"Category": [col("dim_fecha", "Año-Mes")], "Y": [mea("Horas Paro")],
            "Series": [col("dim_causa_paro", "Código")]},
           "Horas de paro por código en el tiempo"),
]

P4 = [  # Producción y planeación
    visual("pivotTable", 20, 130, 1180, 420,
           {"Rows": [col("dim_maquina", "Máquina")], "Columns": [col("dim_fecha", "Año")],
            "Values": [mea("Pacas Producidas")]},
           "Pacas producidas por máquina y año (P-MTO-22)"),
    visual("donutChart", 1220, 130, 680, 420,
           {"Category": [col("dim_estado_turno", "Categoría")], "Y": [mea("Horas No Programadas")]},
           "Horas no programadas por categoría"),
    visual("clusteredBarChart", 20, 570, 940, 490,
           {"Category": [col("dim_referencia", "Referencia")], "Y": [mea("Rendimiento")]},
           "Rendimiento por referencia", sort=(mea("Rendimiento"), "Ascending")),
    visual("pivotTable", 980, 570, 920, 490,
           {"Rows": [col("dim_turno", "Turno")], "Values": [mea("Pacas por Hora"), mea("Disponibilidad")]},
           "Pacas por hora y disponibilidad por turno"),
]

PAGE_DEFS = [("1. Resumen ejecutivo", P1), ("2. Análisis de paros", P2),
             ("3. Mantenimiento", P3), ("4. Producción y planeación", P4)]


def main():
    page_schema, visual_schema = find_template_schemas()
    pages_meta = json.loads((PAGES / "pages.json").read_text(encoding="utf-8"))
    for old in list(PAGES.iterdir()):
        if old.is_dir():
            shutil.rmtree(old)
    order = []
    for display, visuals in PAGE_DEFS:
        name = uuid.uuid4().hex[:20]
        order.append(name)
        pdir = PAGES / name
        (pdir / "visuals").mkdir(parents=True)
        (pdir / "page.json").write_text(json.dumps({
            "$schema": page_schema, "name": name, "displayName": display,
            "displayOption": "FitToPage", "height": 1080, "width": 1920}, ensure_ascii=False, indent=2),
            encoding="utf-8")
        for i, v in enumerate(visuals + common_slicers()):
            vname = uuid.uuid4().hex[:20]
            v["position"]["z"] = i
            v["position"]["tabOrder"] = i
            body = {"$schema": visual_schema, "name": vname, **v}
            (pdir / "visuals" / vname).mkdir()
            (pdir / "visuals" / vname / "visual.json").write_text(
                json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Page '{display}': {len(visuals) + 3} visuals")
    pages_meta["pageOrder"] = order
    pages_meta["activePageName"] = order[0]
    (PAGES / "pages.json").write_text(json.dumps(pages_meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Done. Open powerbi/BI_Paros_Envasado.pbip")


if __name__ == "__main__":
    main()
