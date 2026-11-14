\set ON_ERROR_STOP on
BEGIN;
\ir transform_warehouse.sql
COMMIT;
\ir 04_views.sql
