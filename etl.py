"""Load CSVs with pandas, reuse the SQL warehouse scripts, and audit each run."""

import argparse
import getpass
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pandas as pd
from sqlalchemy import URL, create_engine, text

ROOT = Path(__file__).resolve().parent
FILES = {
    "orders": "olist_orders_dataset.csv",
    "order_items": "olist_order_items_dataset.csv",
    "order_payments": "olist_order_payments_dataset.csv",
    "order_reviews": "olist_order_reviews_dataset.csv",
    "products": "olist_products_dataset.csv",
    "customers": "olist_customers_dataset.csv",
    "sellers": "olist_sellers_dataset.csv",
    "geolocation": "olist_geolocation_dataset.csv",
    "category_translation": "product_category_name_translation.csv",
}
TARGETS = {
    "orders": ("dim_order", "order_key"),
    "customers": ("dim_customer", "customer_key"),
    "sellers": ("dim_seller", "seller_key"),
    "products": ("dim_product", "product_key"),
    "categories": ("dim_product_category", "category_key"),
    "geolocation": ("dim_geolocation", "geo_key"),
    "order_items": ("fact_order_items", "order_item_key"),
    "order_payments": ("fact_order_payments", "payment_key"),
}
REFERENCES = {
    "dim_customer": ("geo_key",),
    "dim_seller": ("geo_key",),
    "dim_product": ("category_key",),
    "dim_order": ("customer_key", "purchase_date_key", "delivered_date_key", "estimated_date_key"),
    "fact_order_items": ("order_key", "product_key", "seller_key"),
    "fact_order_payments": ("order_key",),
}


def connection_settings(args):
    settings = {"PGHOST": "localhost", "PGPORT": "5432", "PGDATABASE": "olist_dw", "PGUSER": "postgres", "PGPASSWORD": ""}
    for key in settings:
        settings[key] = os.environ.get(key, settings[key])
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8-sig").splitlines():
            key, separator, value = line.partition("=")
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            if separator and key.strip() in settings and value:
                settings[key.strip()] = value
    for option, key in (("host", "PGHOST"), ("port", "PGPORT"), ("database", "PGDATABASE"), ("user", "PGUSER")):
        value = getattr(args, option)
        if value is not None:
            settings[key] = str(value)
    if not settings["PGPASSWORD"]:
        settings["PGPASSWORD"] = getpass.getpass("PostgreSQL password: ")
    return settings


def database_engine(settings, database=None):
    # URL.create safely handles passwords containing @, :, /, or other symbols.
    url = URL.create("postgresql+psycopg2", username=settings["PGUSER"],
        password=settings["PGPASSWORD"], host=settings["PGHOST"],
        port=int(settings["PGPORT"]), database=database or settings["PGDATABASE"])
    return create_engine(url, connect_args={"connect_timeout": 10, "client_encoding": "UTF8"}, hide_parameters=True)


def ensure_database(settings):
    admin = database_engine(settings, "postgres")
    try:
        with admin.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            exists = connection.scalar(text("SELECT 1 FROM pg_database WHERE datname=:name"), {"name": settings["PGDATABASE"]})
            if not exists:
                name = admin.dialect.identifier_preparer.quote(settings["PGDATABASE"])
                connection.exec_driver_sql(f"CREATE DATABASE {name}")
    finally:
        admin.dispose()


def run_sql(filename, settings):
    psql = shutil.which("psql") or str(Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "PostgreSQL/18/bin/psql.exe")
    environment = {**os.environ, **settings, "PGCLIENTENCODING": "UTF8", "PGCONNECT_TIMEOUT": "10"}
    result = subprocess.run([psql, "-X", "-w", "-v", "ON_ERROR_STOP=1", "-f", str(ROOT / "sql" / filename)],
        cwd=ROOT, env=environment, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode:
        raise RuntimeError(f"{filename}: {result.stderr.strip()}")


def check_files(data_dir):
    missing = [name for table, name in FILES.items() if table != "geolocation" and not (data_dir / name).is_file()]
    if missing:
        raise FileNotFoundError("Missing required CSVs: " + ", ".join(missing))


def read_chunks(path):
    # Preserve postal-code zeros and literal text such as 'NA'; never infer numbers.
    return pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig", chunksize=50000)


def load_csvs(engine, data_dir):
    # One transaction: a malformed CSV cannot leave staging half-loaded.
    with engine.begin() as connection:
        connection.exec_driver_sql("TRUNCATE " + ", ".join(f"staging.{table}" for table in FILES))
        cursor = connection.connection.driver_connection.cursor()
        try:
            for table, filename in FILES.items():
                path = data_dir / filename
                if table == "geolocation" and not path.is_file():
                    print("  geolocation: absent (optional)", flush=True)
                    continue
                expected = list(connection.exec_driver_sql(f"SELECT * FROM staging.{table} LIMIT 0").keys())
                row_count = 0
                with read_chunks(path) as chunks:
                    for chunk in chunks:
                        if list(chunk.columns) != expected:
                            raise ValueError(f"Unexpected CSV columns in {filename}")
                        buffer = io.StringIO()
                        chunk.to_csv(buffer, index=False, header=False, lineterminator="\n")
                        buffer.seek(0)
                        cursor.copy_expert(f"COPY staging.{table} FROM STDIN WITH (FORMAT CSV, ENCODING 'UTF8')", buffer)
                        row_count += len(chunk)
                print(f"  {table}: {row_count:,} rows", flush=True)
        finally:
            cursor.close()


def audit_counts(engine):
    rows = {"source": {}, "warehouse": {}}
    unknowns = {}
    with engine.connect() as connection:
        for table in FILES:
            rows["source"][table] = connection.scalar(text(f"SELECT count(*) FROM staging.{table}"))
        for label, (table, key) in TARGETS.items():
            rows["warehouse"][label] = connection.scalar(text(f"SELECT count(*) FROM dw.{table} WHERE {key}<>0"))
        for table, columns in REFERENCES.items():
            key = next(key for target, key in TARGETS.values() if target == table)
            for column in columns:
                unknowns[f"{table}.{column}"] = connection.scalar(text(f"SELECT count(*) FROM dw.{table} WHERE {key}<>0 AND {column}=0"))
    return rows, unknowns


def finish_run(engine, run_id, status, stage, rows, unknowns, error=None):
    with engine.begin() as connection:
        connection.execute(text("""
            UPDATE meta.etl_log SET completed_at=clock_timestamp(), status=:status,
                stage=:stage, row_counts=CAST(:rows AS jsonb), unknown_counts=CAST(:unknowns AS jsonb),
                error_message=:error, source_orders=:source_orders, loaded_orders=:loaded_orders,
                loaded_items=:loaded_items, loaded_payments=:loaded_payments
            WHERE run_id=:run_id
        """), {"run_id": run_id, "status": status, "stage": stage, "rows": json.dumps(rows),
            "unknowns": json.dumps(unknowns), "error": error,
            "source_orders": rows.get("source", {}).get("orders"),
            "loaded_orders": rows.get("warehouse", {}).get("orders"),
            "loaded_items": rows.get("warehouse", {}).get("order_items"),
            "loaded_payments": rows.get("warehouse", {}).get("order_payments")})


def run_pipeline(engine, settings, data_dir, reports_only=False):
    # Bootstrap audit storage before schema, extraction, reporting or validation can fail.
    with engine.begin() as connection:
        connection.exec_driver_sql((ROOT / "sql/00_audit.sql").read_text(encoding="utf-8"))
        run_id = connection.scalar(text("""
            INSERT INTO meta.etl_log(started_at,status,run_mode,stage,notes)
            VALUES (clock_timestamp(),'running',:mode,'starting',:notes) RETURNING run_id
        """), {"mode": "reports" if reports_only else "full",
            "notes": "Geolocation file absent" if not reports_only and not (data_dir / FILES["geolocation"]).is_file() else None})
    stage = "starting"
    rows, unknowns = {}, {}
    try:
        if not reports_only:
            stage = "preflight"
            check_files(data_dir)
            stage = "schema"
            print("Preparing warehouse schema...", flush=True)
            run_sql("01_schema.sql", settings)
            stage = "extract"
            print("Loading CSV files with pandas...", flush=True)
            load_csvs(engine, data_dir)
            stage = "transform"
            print("Building warehouse dimensions and facts...", flush=True)
            run_sql("03_transform.sql", settings)
        stage = "reports"
        print("Updating reporting views...", flush=True)
        run_sql("04_views.sql", settings)
        stage = "validation"
        print("Validating row counts, financial totals and unknown members...", flush=True)
        rows, unknowns = audit_counts(engine)
        run_sql("05_validate.sql", settings)
        finish_run(engine, run_id, "success", "complete", rows, unknowns)
        print(f"Run {run_id} succeeded. Audit details: meta.etl_log", flush=True)
        return run_id
    except (Exception, KeyboardInterrupt) as exc:
        message = str(exc) or "Run interrupted"
        if settings["PGPASSWORD"]:
            message = message.replace(settings["PGPASSWORD"], "[redacted]")
        try:
            # Counts on failure describe the database at failure time, not a successful load.
            rows, unknowns = audit_counts(engine)
        except Exception:
            pass
        try:
            finish_run(engine, run_id, "failed", stage, rows, unknowns, message[:4000])
        except Exception:
            print(f"Could not persist failure details for run {run_id}.", file=sys.stderr)
        raise RuntimeError(f"Run {run_id} failed during {stage}: {message}") from None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reports-only", action="store_true")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data/raw")
    for option in ("host", "port", "database", "user"):
        parser.add_argument(f"--{option}")
    args = parser.parse_args()
    settings = connection_settings(args)
    engine = None
    try:
        if not args.reports_only:
            ensure_database(settings)
        engine = database_engine(settings)
        run_pipeline(engine, settings, args.data_dir.resolve(), args.reports_only)
        return 0
    except Exception as exc:
        message = str(exc)
        if settings["PGPASSWORD"]:
            message = message.replace(settings["PGPASSWORD"], "[redacted]")
        print(message, file=sys.stderr)
        return 1
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    sys.exit(main())
