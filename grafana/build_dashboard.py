"""Generates grafana/dashboards/operativo.json (the exported dashboard that Grafana
provisions at start-up). Keeping the panels as code makes the JSON reviewable in
Git; run `python grafana/build_dashboard.py` after changing a panel.
"""
import json
from pathlib import Path

DS = {"type": "grafana-postgresql-datasource", "uid": "pg-dw"}
FILTER = "m.maquina_nk IN ($maquina) AND t.turno_nk IN ($turno)"
FROM_H = ("FROM dw.fact_produccion_hora h\n"
          "JOIN dw.dim_maquina m ON m.maquina_sk = h.maquina_sk\n"
          "JOIN dw.dim_turno   t ON t.turno_sk   = h.turno_sk\n")

OEE_THRESHOLDS = {"mode": "absolute", "steps": [
    {"color": "red", "value": None}, {"color": "orange", "value": 60}, {"color": "green", "value": 75}]}


def target(sql: str, fmt: str = "table", ref: str = "A") -> dict:
    return {"refId": ref, "datasource": DS, "editorMode": "code", "format": fmt, "rawQuery": True, "rawSql": sql}


def panel(pid, title, ptype, grid, targets, field_config=None, options=None, description="", **extra):
    p = {"id": pid, "title": title, "type": ptype, "datasource": DS, "gridPos": grid, "targets": targets,
         "description": description,
         "fieldConfig": field_config or {"defaults": {}, "overrides": []}, "options": options or {}}
    p.update(extra)
    return p


panels = [
    panel(1, "OEE de la última hora por máquina", "stat", {"x": 0, "y": 0, "w": 12, "h": 6},
          [target("SELECT h.ts AS time, m.maquina_nk AS metric, ROUND(h.oee * 100, 1) AS value\n" + FROM_H +
                  f"WHERE $__timeFilter(h.ts) AND {FILTER}\nORDER BY 1", fmt="time_series")],
          {"defaults": {"unit": "percent", "decimals": 1, "min": 0, "max": 100, "thresholds": OEE_THRESHOLDS,
                        "color": {"mode": "thresholds"}}, "overrides": []},
          {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False}, "colorMode": "background",
           "graphMode": "area", "textMode": "value_and_name", "orientation": "auto", "justifyMode": "center"},
          "Último valor de OEE simulado por máquina. Rojo < 60% (umbral de alerta), naranja < 75% (meta)."),

    panel(2, "Estado actual por máquina", "table", {"x": 12, "y": 0, "w": 12, "h": 6},
          [target('SELECT maquina_nk AS "Máquina", estado AS "Estado", modo_simulacion AS "Modo",\n'
                  '       turno_nk AS "Turno", ROUND(oee * 100, 1) AS "OEE %", pacas AS "Pacas",\n'
                  '       pacas_meta AS "Meta", minutos_paro_no_planif AS "Min. paro",\n'
                  '       causa_principal AS "Causa principal", hora_simulada AS "Hora planta"\n'
                  "FROM dw.vw_rt_estado_actual\nWHERE maquina_nk IN ($maquina)\nORDER BY 1")],
          {"defaults": {"custom": {"align": "auto", "cellOptions": {"type": "auto"}}},
           "overrides": [
               {"matcher": {"id": "byName", "options": "Estado"}, "properties": [
                   {"id": "custom.cellOptions", "value": {"type": "color-background", "mode": "basic"}},
                   {"id": "mappings", "value": [{"type": "value", "options": {
                       "OK": {"color": "green", "index": 0}, "BAJO META": {"color": "orange", "index": 1},
                       "CRÍTICO": {"color": "red", "index": 2}, "PARADA": {"color": "dark-red", "index": 3}}}]}]},
               {"matcher": {"id": "byName", "options": "OEE %"}, "properties": [
                   {"id": "custom.cellOptions", "value": {"type": "color-text"}},
                   {"id": "thresholds", "value": OEE_THRESHOLDS}, {"id": "unit", "value": "percent"}]}]},
          {"showHeader": True, "cellHeight": "sm"},
          "Último registro de cada máquina (vista dw.vw_rt_estado_actual)."),

    panel(3, "OEE por hora", "timeseries", {"x": 0, "y": 6, "w": 16, "h": 9},
          [target("SELECT h.ts AS time, m.maquina_nk AS metric, ROUND(h.oee * 100, 1) AS value\n" + FROM_H +
                  f"WHERE $__timeFilter(h.ts) AND {FILTER}\nORDER BY 1", fmt="time_series")],
          {"defaults": {"unit": "percent", "min": 0, "max": 110, "thresholds": OEE_THRESHOLDS,
                        "custom": {"drawStyle": "line", "lineWidth": 2, "pointSize": 4, "showPoints": "always",
                                   "thresholdsStyle": {"mode": "dashed+area"}, "fillOpacity": 0}},
           "overrides": []},
          {"legend": {"displayMode": "table", "placement": "right", "calcs": ["lastNotNull", "mean", "min"]},
           "tooltip": {"mode": "multi", "sort": "desc"}},
          "Cada punto es una hora simulada. La franja roja marca el umbral de alerta (60%)."),

    panel(4, "Disponibilidad · Rendimiento · Calidad (rango visible)", "gauge", {"x": 16, "y": 6, "w": 8, "h": 9},
          [target('SELECT ROUND(100 * SUM(h.minutos_operativos) / NULLIF(SUM(60 - h.minutos_planificados), 0), 1) AS "Disponibilidad",\n'
                  '       ROUND(100 * SUM(h.pacas) / NULLIF(SUM(h.pacas_ideales), 0), 1) AS "Rendimiento",\n'
                  '       ROUND(100 * AVG(h.calidad), 1) AS "Calidad"\n' + FROM_H +
                  f"WHERE $__timeFilter(h.ts) AND {FILTER}")],
          {"defaults": {"unit": "percent", "min": 0, "max": 100, "decimals": 1, "thresholds": {
              "mode": "absolute", "steps": [{"color": "red", "value": None}, {"color": "orange", "value": 70},
                                            {"color": "green", "value": 85}]}}, "overrides": []},
          {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
           "showThresholdMarkers": True, "orientation": "vertical"},
          "Componentes del OEE agregados como razón de sumas (no promedio de porcentajes)."),

    panel(5, "Pacas producidas vs meta horaria", "timeseries", {"x": 0, "y": 15, "w": 12, "h": 8},
          [target('SELECT h.ts AS time, SUM(h.pacas) AS "Pacas producidas", SUM(h.pacas_meta) AS "Meta (85% ideal)"\n'
                  + FROM_H + f"WHERE $__timeFilter(h.ts) AND {FILTER}\nGROUP BY h.ts\nORDER BY 1",
                  fmt="time_series")],
          {"defaults": {"unit": "short", "custom": {"drawStyle": "bars", "fillOpacity": 60, "lineWidth": 1}},
           "overrides": [{"matcher": {"id": "byName", "options": "Meta (85% ideal)"}, "properties": [
               {"id": "custom.drawStyle", "value": "line"}, {"id": "custom.lineWidth", "value": 2},
               {"id": "custom.lineStyle", "value": {"fill": "dash", "dash": [10, 10]}},
               {"id": "color", "value": {"mode": "fixed", "fixedColor": "yellow"}}]}]},
          {"legend": {"displayMode": "list", "placement": "bottom"}, "tooltip": {"mode": "multi"}}),

    panel(6, "Minutos de paro no planificado por causa", "bargauge", {"x": 12, "y": 15, "w": 12, "h": 8},
          [target('SELECT COALESCE(c.codigo_label, \'Sin paro\') AS "Causa", SUM(h.minutos_paro_no_planif) AS "Minutos"\n'
                  + FROM_H + "LEFT JOIN dw.dim_causa_paro c ON c.causa_sk = h.causa_principal_sk\n"
                  f"WHERE $__timeFilter(h.ts) AND {FILTER} AND h.minutos_paro_no_planif > 0\n"
                  "GROUP BY 1\nORDER BY 2 DESC\nLIMIT 8")],
          {"defaults": {"unit": "m", "color": {"mode": "continuous-YlRd"}, "min": 0}, "overrides": []},
          {"reduceOptions": {"calcs": [], "fields": "/Minutos/", "values": True}, "orientation": "horizontal",
           "displayMode": "gradient", "showUnfilled": True, "namePlacement": "left"}),

    panel(7, "Alertas recibidas (webhook)", "table", {"x": 0, "y": 23, "w": 12, "h": 8},
          [target('SELECT recibida_en AS "Recibida", estado AS "Estado", maquina AS "Máquina",\n'
                  '       regla AS "Regla", valor AS "Valor"\n'
                  "FROM ops.alertas_recibidas\nORDER BY alerta_id DESC\nLIMIT 20")],
          {"defaults": {}, "overrides": [{"matcher": {"id": "byName", "options": "Estado"}, "properties": [
              {"id": "custom.cellOptions", "value": {"type": "color-background", "mode": "basic"}},
              {"id": "mappings", "value": [{"type": "value", "options": {
                  "firing": {"color": "red", "text": "DISPARADA", "index": 0},
                  "resolved": {"color": "green", "text": "RESUELTA", "index": 1}}}]}]}]},
          {"showHeader": True, "cellHeight": "sm"},
          "Notificaciones que Grafana envió al contact point (servicio alert-sink -> ops.alertas_recibidas)."),

    panel(8, "Contexto histórico: OEE mensual por máquina", "timeseries", {"x": 12, "y": 23, "w": 12, "h": 8},
          [target("SELECT make_date(anio, mes, 1)::timestamptz AS time, maquina_nk AS metric,\n"
                  "       ROUND(oee * 100, 1) AS value\nFROM dw.vw_kpi_mensual_maquina\n"
                  "WHERE oee IS NOT NULL AND maquina_nk IN ($maquina)\nORDER BY 1", fmt="time_series")],
          {"defaults": {"unit": "percent", "min": 0, "max": 110, "thresholds": OEE_THRESHOLDS,
                        "custom": {"drawStyle": "line", "lineWidth": 2, "showPoints": "always",
                                   "thresholdsStyle": {"mode": "dashed"}}}, "overrides": []},
          {"legend": {"displayMode": "list", "placement": "bottom"}, "tooltip": {"mode": "multi"}},
          "Datos históricos del ETL (2023–2025) para comparar el tiempo real con la línea base.",
          timeFrom="5y", hideTimeOverride=False),
]


def variable(name, label, sql):
    return {"name": name, "label": label, "type": "query", "datasource": DS, "query": sql, "definition": sql,
            "multi": True, "includeAll": True, "refresh": 1, "sort": 1,
            "current": {"selected": True, "text": ["All"], "value": ["$__all"]}, "options": []}


dashboard = {
    "uid": "oee-operativo",
    "title": "Monitoreo operativo — Líneas de envasado",
    "description": "Tablero near real time: OEE hora a hora, estado por máquina y alertas (datos simulados).",
    "tags": ["oee", "envasado", "operativo"],
    "timezone": "browser",
    "editable": True,
    "graphTooltip": 1,
    "refresh": "10s",
    "time": {"from": "now-30m", "to": "now"},
    "timepicker": {"refresh_intervals": ["5s", "10s", "30s", "1m", "5m"]},
    "schemaVersion": 39,
    "version": 1,
    "templating": {"list": [
        variable("maquina", "Máquina", "SELECT maquina_nk FROM dw.dim_maquina WHERE es_actual ORDER BY 1"),
        variable("turno", "Turno", "SELECT turno_nk FROM dw.dim_turno WHERE turno_sk BETWEEN 1 AND 3 ORDER BY turno_sk"),
    ]},
    "annotations": {"list": [{"builtIn": 1, "datasource": {"type": "grafana", "uid": "-- Grafana --"},
                              "enable": True, "hide": True, "iconColor": "rgba(0, 211, 255, 1)",
                              "name": "Annotations & Alerts", "type": "dashboard"}]},
    "panels": panels,
}

out = Path(__file__).parent / "dashboards" / "operativo.json"
out.write_text(json.dumps(dashboard, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"Written {out}")
