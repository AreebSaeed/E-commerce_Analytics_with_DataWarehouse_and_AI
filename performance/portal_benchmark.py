"""Measure local dashboard HTTP responses; start web/predict_api.py first."""

import json
from time import perf_counter
from urllib.request import Request, urlopen

BASE = "http://127.0.0.1:8000"


def get(path):
    with urlopen(BASE + path, timeout=10) as response:
        return response.read()


def post_prediction(body):
    request = Request(BASE + "/api/predict", data=json.dumps(body).encode(),
                      headers={"Content-Type": "application/json"}, method="POST")
    with urlopen(request, timeout=10) as response:
        return json.load(response)


def measure(label, action):
    action()  # warm up the server and model pipeline
    times = []
    for _ in range(5):
        start = perf_counter()
        action()
        times.append((perf_counter() - start) * 1000)
    print(f"{label}: max {max(times):.1f} ms across 5 warm requests")


def main():
    model = json.loads(get("/api/model"))
    state = "SP" if "SP" in model["states"] else model["states"][0]
    example = {
        "purchase_month": 6, "purchase_weekday": 1,
        "customer_state": state, "seller_state": state,
        "seller_customer_distance_km": 200, "item_count": 1,
        "item_price": 100, "freight_value": 20,
        "total_weight_g": 500, "weight_known_items": 1,
        "total_volume_cm3": 5000, "volume_known_items": 1,
    }
    measure("Dashboard HTML", lambda: get("/"))
    measure("Dashboard snapshot", lambda: get("/dashboard.json"))
    measure("Model metadata", lambda: get("/api/model"))
    measure("What-if prediction", lambda: post_prediction(example))


if __name__ == "__main__":
    main()
