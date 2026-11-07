# BI de paros y productividad — Líneas de envasado de vinilos

End-to-end Business Intelligence solution for the four vinyl/tempera filling lines (Vinilos_1 … Vinilos_4). It turns the stoppage and production logbook (an Excel workbook with macros, procedure P-MTO-22) into a **PostgreSQL dimensional model** that feeds two consumption layers:

- **Power BI**: strategic analysis for the monthly management committee (OEE trends, Pareto of causes, drill-down of the stoppage hierarchy).
- **Grafana**: near-real-time monitoring for supervisors and maintenance (hourly OEE, current state per machine, alerts).

Course: Inteligencia de Negocios (ET0194) · Taller 5 · Institución Universitaria Pascual Bravo · 2026-2
Author: Brayan Romero Dorado

---

## Architecture

```mermaid
flowchart LR
    subgraph Source
        X[("SEGUIMIENTO TEMPERAS Y VINILOS<br/>.xlsm (P-MTO-22)")]
    end
    subgraph Docker["docker compose (one command)"]
        E["etl<br/>Python: extract · pseudonymize ·<br/>clean · unpivot · reconcile"]
        DB[("PostgreSQL 16<br/>stg · dw · etl · sim · ops")]
        S["simulator<br/>1 plant hour every N s"]
        G["Grafana 11<br/>provisioned datasource,<br/>dashboard and alert rule"]
        A["alert-sink<br/>webhook → ops.alertas_recibidas"]
    end
    subgraph Host["Host (Windows)"]
        PBI["Power BI Desktop<br/>(PBIP project)"]
        DBV["DBeaver"]
    end
    X -->|read-only mount| E --> DB
    S -->|INSERT hourly facts| DB
    DB -->|grafana_ro| G -->|OEE < 60% · 2 h| A --> DB
    DB -->|powerbi_ro · Import| PBI
    DBV -->|admin| DB
```

| Layer | Question it answers | User | Refresh |
|---|---|---|---|
| Grafana | "What is happening on the lines right now?" | Supervisor, maintenance | Every 10 s (one simulated hour every 30 s) |
| Power BI | "Why are we losing capacity and where should we invest?" | Management, maintenance coordinator, planning | Monthly / on demand |

---

## Repository layout

```
├── docker-compose.yml          # db, etl, simulator, alert-sink, grafana (+ optional cloudbeaver)
├── .env.example                # copy to .env (git-ignored)
├── data/raw/                   # put the Excel here (git-ignored: personal data)
├── sql/
│   ├── init/                   # DDL executed automatically on an empty volume
│   │   ├── 01_schemas.sql … 06_views.sql
│   │   └── 99_roles.sh         # least-privilege users from env vars
│   ├── queries/                # analytical queries + reconciliation (run from DBeaver)
│   └── demo/                   # SCD2 demo and live simulator scenarios
├── etl/                        # Python ETL, simulator and alert sink (one image)
├── grafana/
│   ├── provisioning/           # datasource, dashboard provider, alert rule, contact point
│   ├── dashboards/operativo.json
│   └── build_dashboard.py      # generates the dashboard JSON
├── cloudbeaver/initial-data-sources.conf   # optional web DBeaver: provisioned connection
├── powerbi/                    # Power BI project in PBIP format (text, Git-friendly)
└── docs/                       # design, data dictionary, ETL and data quality
```

---

## Reproduce from scratch

Requirements on the host: **Docker Desktop** (running), **Git**, **Power BI Desktop** and **DBeaver Community**. Power BI and DBeaver run on the host and connect to the containers.

### 1. Server side — one command

```powershell
git clone https://github.com/romerobrayan/bi-paros-envasado.git
cd bi-paros-envasado
copy .env.example .env          # Linux/macOS: cp .env.example .env  (change every CHANGE_ME value)
# copy "SEGUIMIENTO TEMPERAS Y VINILOS Actividad.xlsm" into data\raw\  (not versioned: personal data)
docker compose up -d --build
```

`docker compose up -d --build` is the only command needed to build and start everything. The first run downloads the images and takes a few minutes; later runs take seconds.

What happens:
1. `db` creates the schemas, tables, indexes, views and the three least-privilege users (only the first time, on an empty volume).
2. `etl` loads the warehouse, prints the rule counts and the reconciliation, and exits with code 0. If the workbook has a different name but is the only `.xlsm`/`.xlsx` in `data/raw/`, it is used anyway.
3. `simulator` starts after the ETL finishes and writes one simulated plant hour per machine every `SIM_TICK_SECONDS`.
4. `grafana` starts already connected to PostgreSQL, with the dashboard, the alert rule and the contact point loaded. There is nothing to configure by hand.

If `.env` is missing, Compose stops before starting anything and names the missing variable.

Check that it worked:

```powershell
docker compose ps -a              # etl "Exited (0)", the rest "Up"
docker compose logs etl           # ends with "ETL OK" and the reconciliation table
```

### 2. Clients on the host

| Tool | Connection |
|---|---|
| Grafana | http://localhost:3000 — user/password `GRAFANA_ADMIN_*` from `.env`; the dashboard *Monitoreo operativo — Líneas de envasado* opens as home |
| DBeaver | PostgreSQL, host `localhost`, port `DB_PORT` (5433), database `bi_paros`, user `POSTGRES_USER`, password `POSTGRES_PASSWORD` |
| Power BI | open `powerbi/BI_Paros_Envasado.pbip`; when asked for credentials choose **Base de datos**, user `powerbi_ro`, password `POWERBI_DB_PASSWORD`; then **Inicio → Actualizar** |

The Power BI project points to `localhost:5433`. If you use another `DB_PORT`, change it in **Transformar datos → Configuración de origen de datos → Cambiar origen**.

Optional web DBeaver (CloudBeaver), with the connection already defined: `docker compose --profile tools up -d` → http://localhost:8978 (127.0.0.1 only). On the first start it asks for its own admin user. If opening the connection says *Driver disabled*, go to **Administration → Server Configuration → Disabled drivers**, remove PostgreSQL and save.

### 3. Useful commands

```powershell
docker compose run --rm etl        # re-run only the ETL (full refresh, same result)
docker compose down                # stop, keep data (volumes)
docker compose down -v             # stop and delete data -> next "up" rebuilds everything from zero
```

Troubleshooting: if port 5433 or 3000 is taken, change `DB_PORT` / `GRAFANA_PORT` in `.env`. If the ETL could not find the workbook, copy it into `data/raw/` and run `docker compose up -d` again.

---

## Live demo (Grafana reacts to the simulator)

From DBeaver run `sql/demo/02_escenarios_simulador.sql`:

```sql
UPDATE sim.control SET modo = 'falla', actualizado = now() WHERE maquina_nk = 'Vinilos_2';
```

Within about a minute (two simulated hours), the OEE of Vinilos_2 turns red and the alert **"OEE por debajo de 60% durante 2 horas"** fires. The notification shows up in the panel *Alertas recibidas*. Run `modo = 'normal'` and the alert resolves.

Modes: `normal`, `falla` (code 01), `lenta` (code 05 | 5.2 dosing system), `parada` (code 14, no raw material).

---

## Data model (summary)

Kimball constellation with three facts and conformed dimensions. Full details: [docs/01-design.md](docs/01-design.md), [docs/02-data-dictionary.md](docs/02-data-dictionary.md).

| Fact | Grain |
|---|---|
| `dw.fact_produccion_turno` | one shift form: machine × date × shift × operator × reference |
| `dw.fact_paro` | one stoppage cause inside one source record (unpivot of 18 code columns) |
| `dw.fact_produccion_hora` | one machine × one simulated hour (near real time) |

Dimensions: `dim_fecha` (built by us, with Colombian holidays), `dim_turno`, `dim_maquina` (**SCD2**), `dim_referencia`, `dim_persona` (role-playing, pseudonymized), `dim_causa_paro` (hierarchy Área → Código → Sistema → Componente), `dim_estado_turno`.

OEE = Availability × Performance × Quality. The time model and the indicator catalog are in [docs/01-design.md §3](docs/01-design.md).

---

## Security and personal data

- **Ley 1581 de 2012.** Operator and maintenance staff names are replaced by `PER-xxxxxx` (salted SHA-256) **before** they are written to the database. The salt lives in `.env`.
- The Excel source is git-ignored. No password or connection string is versioned; `.env.example` holds only placeholders.
- **Least privilege:** `etl_user` (read/write), `grafana_ro` (read-only on `dw`, `sim`, `ops`) and `powerbi_ro` (read-only on `dw`). The admin user is only for DBeaver.
- Grafana: sign-up and anonymous access disabled; the admin password comes from `.env`.
- CloudBeaver (optional): published on `127.0.0.1` only, anonymous access disabled, and the provisioned connection does not save the database password.

---

## Documentation

| Document | Content |
|---|---|
| [01-design.md](docs/01-design.md) | Users, business questions, source diagnosis, KPI catalog, dimensional model, bus matrix, SCD |
| [02-data-dictionary.md](docs/02-data-dictionary.md) | Every table: columns, types, keys, transformation rules, lineage |
| [03-etl-and-data-quality.md](docs/03-etl-and-data-quality.md) | ETL design, cleaning rules with counts, reconciliation |
| [04-powerbi-guide.md](docs/04-powerbi-guide.md) | Power BI connection, relationships, DAX measures (`powerbi/medidas.dax`) and report pages |
