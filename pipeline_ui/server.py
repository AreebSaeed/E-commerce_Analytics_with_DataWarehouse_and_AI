"""Serve the loopback control panel and stream output from fixed pipeline commands."""

from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
from threading import Lock, Thread
import webbrowser


HOST = "127.0.0.1"
PORT = 8765
ADDRESS = f"{HOST}:{PORT}"
URL = f"http://{ADDRESS}"
DASHBOARD_URL = "http://127.0.0.1:8000/"
STATIC = Path(__file__).resolve().parent
ASSETS = {
    "/": (STATIC / "index.html", "text/html"),
    "/panel.css": (STATIC / "panel.css", "text/css"),
    "/panel.js": (STATIC / "panel.js", "text/javascript"),
    "/olist-brand.css": (STATIC.parent / "web/public/olist-brand.css", "text/css"),
}


class Pipeline:
    def __init__(self, stages, command_for):
        self.stages = stages
        self.command_for = command_for
        self.states = [
            {"id": key, "title": title, "status": "pending", "lines": deque(maxlen=500)}
            for key, title, _ in stages
        ]
        self.lock = Lock()
        self.process = None
        self.closing = False

    def snapshot(self):
        with self.lock:
            running = any(item["status"] == "running" for item in self.states)
            next_id = next((item["id"] for item in self.states if item["status"] != "succeeded"), None)
            return {
                "next": None if running else next_id,
                "stages": [{**item, "lines": list(item["lines"])} for item in self.states],
                "dashboard": DASHBOARD_URL if self.states[-1]["status"] == "succeeded" else None,
            }

    def start(self, key):
        with self.lock:
            if key not in {stage[0] for stage in self.stages}:
                return 404, "Unknown pipeline stage."
            if self.closing or any(item["status"] == "running" for item in self.states):
                return 409, "Wait for the current stage to finish."
            index = next(
                (index for index, item in enumerate(self.states) if item["status"] != "succeeded"),
                None
            )
            if index is None or self.states[index]["id"] != key:
                return 409, "Run the stages in order."
            state = self.states[index]
            state["lines"].clear()
            state["status"] = "running"
            Thread(target=self.run, args=(self.stages[index], state), daemon=True).start()
        return 202, "Stage started."

    def run(self, stage, state):
        def log(line):
            with self.lock:
                state["lines"].append(line)

        def run_command(command, directory, dashboard=False):
            with self.lock:
                if self.closing:
                    raise RuntimeError("The control panel is closing.")
                process = subprocess.Popen(
                    command, cwd=directory, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT, encoding="utf-8", errors="replace",
                    env={**os.environ, "PYTHONIOENCODING": "utf-8", "NO_COLOR": "1"},
                )
                self.process = process
            try:
                with process.stdout:
                    for line in process.stdout:
                        line = line.rstrip()
                        if line:
                            log(line)
                        if dashboard and line.startswith("Dashboard and prediction API:"):
                            with self.lock:
                                state["status"] = "succeeded"
                code = process.wait()
                if code:
                    raise RuntimeError(f"Process exited with code {code}.")
                if dashboard:
                    raise RuntimeError("The dashboard server stopped. Run this stage again to restart it.")
            finally:
                with self.lock:
                    if self.process is process:
                        self.process = None

        try:
            command, directory = self.command_for(stage, run_command, log)
            run_command(command, directory, dashboard=stage[0] == "dashboard")
        except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
            log(str(error))
            if stage[0] == "warehouse" and any("EOFError" in line for line in state["lines"]):
                log("Set PGPASSWORD in the project's .env file, then retry this stage.")
            with self.lock:
                state["status"] = "failed"
        else:
            with self.lock:
                state["status"] = "succeeded"

    def close(self):
        with self.lock:
            self.closing = True
            process = self.process
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


class ControlPanelHandler(BaseHTTPRequestHandler):
    def reply(self, status, body, content_type):
        self.send_response(status)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; style-src 'self' https://fonts.googleapis.com; "
            "font-src https://fonts.gstatic.com; frame-ancestors 'none'",
        )
        self.end_headers()
        self.wfile.write(body)

    def reply_json(self, status, payload):
        self.reply(status, json.dumps(payload).encode("utf-8"), "application/json")

    def do_GET(self):
        if self.headers.get("Host") != ADDRESS:
            self.reply_json(403, {"message": "Open the control panel at its local address."})
        elif self.path == "/api/status":
            self.reply_json(200, self.server.pipeline.snapshot())
        elif self.path in ASSETS:
            asset, content_type = ASSETS[self.path]
            self.reply(200, asset.read_bytes(), content_type)
        else:
            self.reply_json(404, {"message": "Not found."})

    def do_POST(self):
        if (self.headers.get("Host") != ADDRESS
                or self.headers.get("Origin", URL) != URL
                or self.headers.get("X-Olist-Request") != "stage"):
            self.reply_json(403, {"message": "Start stages from the local control panel."})
            return
        prefix = "/api/run/"
        if not self.path.startswith(prefix):
            self.reply_json(404, {"message": "Not found."})
            return
        status, message = self.server.pipeline.start(self.path.removeprefix(prefix))
        self.reply_json(status, {"message": message})

    def log_message(self, _format, *_args):
        pass


def serve(stages, command_for):
    pipeline = Pipeline(stages, command_for)
    try:
        with ThreadingHTTPServer((HOST, PORT), ControlPanelHandler) as server:
            server.pipeline = pipeline
            print(f"Pipeline control panel: {URL}/", flush=True)
            print("Press Ctrl+C to stop the control panel and any server it started.", flush=True)
            Thread(target=webbrowser.open, args=(URL,), daemon=True).start()
            server.serve_forever()
    except KeyboardInterrupt:
        print("\nPipeline control panel stopped.", flush=True)
    except OSError as error:
        print(f"Could not start the control panel at {URL}: {error}", flush=True)
        return 1
    finally:
        pipeline.close()
    return 0
