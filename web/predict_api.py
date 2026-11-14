"""Small local HTTP server for the TypeScript dashboard and saved delivery model."""

import json
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import joblib
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DIST = Path(__file__).resolve().parent / "dist"
REPORTS = ROOT / "models"


def load_model():
    reports = sorted(REPORTS.glob("delivery_*.json"), reverse=True)
    for report_path in reports:
        model_path = report_path.with_suffix(".joblib")
        if model_path.exists():
            report = json.loads(report_path.read_text(encoding="utf-8"))
            saved = joblib.load(model_path)  # Load only our own local training artifact.
            encoder = saved["model"].named_steps["preprocess"].named_transformers_["states"].named_steps["encode"]
            states = sorted({str(value) for categories in encoder.categories_ for value in categories if str(value) != "Unknown"})
            return report, saved, states
    raise FileNotFoundError("No delivery model found. Run train_delivery.py first.")


REPORT, SAVED, STATES = load_model()
NUMERIC = [name for name in SAVED["features"] if name not in ("customer_state", "seller_state")]


def predict(payload):
    if not isinstance(payload, dict) or set(payload) != set(SAVED["features"]):
        raise ValueError("Please provide every model input.")
    row = {}
    for name in NUMERIC:
        value = payload[name]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not float(value) >= 0 or not float(value) < float("inf"):
            raise ValueError(f"Invalid value for {name}.")
        row[name] = value
    if not 1 <= row["purchase_month"] <= 12 or not 1 <= row["purchase_weekday"] <= 7:
        raise ValueError("Invalid purchase month or weekday.")
    for name in ("item_count", "weight_known_items", "volume_known_items"):
        if row[name] != int(row[name]):
            raise ValueError(f"{name} must be a whole number.")
    if row["item_count"] < 1 or any(row[name] > row["item_count"] for name in ("weight_known_items", "volume_known_items")):
        raise ValueError("Measurement counts cannot exceed item count.")
    for name in ("customer_state", "seller_state"):
        if payload[name] not in STATES:
            raise ValueError(f"Choose a valid {name}.")
        row[name] = payload[name]
    probability = float(SAVED["model"].predict_proba(pd.DataFrame([row], columns=SAVED["features"]))[0, 1])
    threshold = float(SAVED["threshold"])
    band = "Low" if probability < threshold / 2 else "Medium" if probability < threshold else "High"
    return {"late_probability": probability, "predicted_late": probability >= threshold,
            "risk_band": band, "threshold": threshold, "model_version": REPORT["version"]}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DIST), **kwargs)

    def json_response(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/api/model":
            self.json_response(200, {"version": REPORT["version"], "selected_model": REPORT["selected_model"],
                "train_rows": REPORT["train_rows"], "validation_rows": REPORT["validation"][REPORT["selected_model"]]["rows"],
                "test": REPORT["test"], "threshold": REPORT["threshold"], "training_cutoff": REPORT["training_cutoff"],
                "test_cutoff": REPORT["test_cutoff"], "states": STATES})
            return
        super().do_GET()

    def do_POST(self):
        if self.path != "/api/predict":
            self.json_response(404, {"error": "Not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 4096:
                raise ValueError("Invalid request size.")
            payload = json.loads(self.rfile.read(length))
            self.json_response(200, predict(payload))
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            self.json_response(400, {"error": str(error)})


if __name__ == "__main__":
    if not DIST.is_dir():
        raise SystemExit("Build the dashboard first: cd web; npm.cmd run build")
    server = ThreadingHTTPServer(("127.0.0.1", 8000), Handler)
    print("Dashboard and prediction API: http://127.0.0.1:8000", flush=True)
    server.serve_forever()
