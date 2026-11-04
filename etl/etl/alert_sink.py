"""Minimal webhook receiver for Grafana alert notifications — python -m etl.alert_sink

Grafana's contact point posts here; each alert is stored in ops.alertas_recibidas
so the operational dashboard can show that the alert actually fired (and resolved).
"""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, HTTPServer

import psycopg2
from psycopg2.extras import Json

from .config import settings


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)) or 0)
        try:
            payload = json.loads(body or b"{}")
            alerts = payload.get("alerts", []) or [payload]
            with psycopg2.connect(settings.dsn()) as conn, conn.cursor() as cur:
                for a in alerts:
                    labels = a.get("labels", {})
                    values = a.get("values") or {}
                    cur.execute("""INSERT INTO ops.alertas_recibidas (estado, regla, maquina, valor, payload)
                                   VALUES (%s, %s, %s, %s, %s)""",
                                (a.get("status", payload.get("status")), labels.get("alertname"),
                                 labels.get("maquina"), json.dumps(values) if values else a.get("valueString"),
                                 Json(a)))
            print(f"Stored {len(alerts)} alert(s): {payload.get('status')}")
            self.send_response(200)
        except Exception as exc:  # noqa: BLE001
            print(f"Alert sink error: {exc}")
            self.send_response(500)
        self.end_headers()

    def do_GET(self):  # noqa: N802  (health check)
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *args):  # silence default access log
        pass


if __name__ == "__main__":
    print(f"Alert sink listening on :{settings.alert_sink_port}")
    HTTPServer(("0.0.0.0", settings.alert_sink_port), Handler).serve_forever()
