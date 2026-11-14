CREATE SCHEMA IF NOT EXISTS meta;
CREATE TABLE IF NOT EXISTS meta.etl_log (
    run_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    started_at timestamptz DEFAULT clock_timestamp(), completed_at timestamptz,
    status text, source_orders bigint, loaded_orders bigint,
    loaded_items bigint, loaded_payments bigint, notes text
);
-- Keep existing history and add details needed by the Python runner.
ALTER TABLE meta.etl_log ADD COLUMN IF NOT EXISTS run_mode text;
ALTER TABLE meta.etl_log ADD COLUMN IF NOT EXISTS stage text;
ALTER TABLE meta.etl_log ADD COLUMN IF NOT EXISTS row_counts jsonb;
ALTER TABLE meta.etl_log ADD COLUMN IF NOT EXISTS unknown_counts jsonb;
ALTER TABLE meta.etl_log ADD COLUMN IF NOT EXISTS error_message text;
