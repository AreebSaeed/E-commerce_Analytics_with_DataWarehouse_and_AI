"""Small tests for CSV preservation and audit success/failure handling."""
import argparse
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import etl


class EtlTests(unittest.TestCase):
    def test_csv_keeps_postal_zeros_and_literal_text(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "sample.csv"
            path.write_text(
                'zip,comment,empty\n01234,"Sao Paulo, café\nsecond line",\n00001,NA,\n',
                encoding="utf-8",
                newline=""
            )
            with etl.read_chunks(path) as chunks:
                data = next(chunks)
            self.assertEqual(data["zip"].tolist(), ["01234", "00001"])
            self.assertEqual(data.loc[0, "comment"], "Sao Paulo, café\nsecond line")
            self.assertEqual(data.loc[1, "comment"], "NA")
            self.assertEqual(data.loc[0, "empty"], "")

    def test_env_is_literal_and_cli_overrides_it(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / ".env").write_text(
                'PGDATABASE=from_file\nPGPASSWORD="p@ss:$word#123"\n',
                encoding="utf-8"
            )
            args = argparse.Namespace(host=None, port=None, database="from_cli", user=None)
            with patch.object(etl, "ROOT", root), patch.dict(etl.os.environ, {}, clear=True):
                settings = etl.connection_settings(args)
            self.assertEqual(settings["PGDATABASE"], "from_cli")
            self.assertEqual(settings["PGPASSWORD"], "p@ss:$word#123")

    def test_reports_succeed_only_after_validation(self):
        engine = MagicMock()
        engine.begin.return_value.__enter__.return_value.scalar.return_value = 42
        calls = []
        with patch.object(etl, "run_sql", side_effect=lambda file, settings: calls.append(file)), \
             patch.object(etl, "audit_counts", return_value=({"source": {}}, {})), \
             patch.object(etl, "finish_run", side_effect=lambda *args: calls.append(args[2])):
            etl.run_pipeline(engine, {"PGPASSWORD": "secret"}, Path("unused"), reports_only=True)
        self.assertEqual(calls, ["04_views.sql", "05_validate.sql", "success"])

    def test_validation_failure_is_logged_and_password_redacted(self):
        engine = MagicMock()
        engine.begin.return_value.__enter__.return_value.scalar.return_value = 42
        def run_sql(file, settings):
            if file == "05_validate.sql":
                raise RuntimeError("validation failed: secret")
        with patch.object(etl, "run_sql", side_effect=run_sql), \
             patch.object(etl, "audit_counts", return_value=({}, {"dim_product.category_key": 3})), \
             patch.object(etl, "finish_run") as finish:
            with self.assertRaisesRegex(RuntimeError, "failed during validation") as error:
                etl.run_pipeline(engine, {"PGPASSWORD": "secret"}, Path("unused"), reports_only=True)
        self.assertNotIn("secret", str(error.exception))
        self.assertEqual(finish.call_args.args[2:4], ("failed", "validation"))
        self.assertEqual(finish.call_args.args[5], {"dim_product.category_key": 3})
        self.assertNotIn("secret", finish.call_args.args[6])

    def test_missing_files_are_logged_before_loading(self):
        engine = MagicMock()
        engine.begin.return_value.__enter__.return_value.scalar.return_value = 42
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(etl, "audit_counts", return_value=({}, {})), \
             patch.object(etl, "load_csvs") as load, patch.object(etl, "finish_run") as finish:
            with self.assertRaisesRegex(RuntimeError, "failed during preflight"):
                etl.run_pipeline(engine, {"PGPASSWORD": "secret"}, Path(folder))
        load.assert_not_called()
        self.assertEqual(finish.call_args.args[2:4], ("failed", "preflight"))


if __name__ == "__main__":
    unittest.main()
