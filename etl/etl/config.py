"""Runtime configuration, read only from environment variables (.env)."""
import os
from dataclasses import dataclass


def _env(name: str, default: str | None = None, required: bool = False) -> str:
    value = os.getenv(name, default)
    if required and not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value  # type: ignore[return-value]


@dataclass(frozen=True)
class Settings:
    db_host: str = _env("DB_HOST", "localhost")
    db_port: int = int(_env("DB_PORT", "5432"))
    db_name: str = _env("POSTGRES_DB", "bi_paros")
    db_user: str = _env("ETL_DB_USER", "etl_user")
    db_password: str = _env("ETL_DB_PASSWORD", "")
    source_file: str = _env("SOURCE_FILE", "/data/raw/SEGUIMIENTO TEMPERAS Y VINILOS Actividad.xlsm")
    pseudonym_salt: str = _env("PSEUDONYM_SALT", "")
    calendar_from: str = _env("CALENDAR_FROM", "2022-01-01")
    calendar_to: str = _env("CALENDAR_TO", "2027-12-31")
    # simulator
    sim_tick_seconds: int = int(_env("SIM_TICK_SECONDS", "30"))
    sim_seed: int = int(_env("SIM_SEED", "42"))
    # alert sink
    alert_sink_port: int = int(_env("ALERT_SINK_PORT", "8085"))

    def dsn(self) -> str:
        return (f"host={self.db_host} port={self.db_port} dbname={self.db_name} "
                f"user={self.db_user} password={self.db_password}")


settings = Settings()
