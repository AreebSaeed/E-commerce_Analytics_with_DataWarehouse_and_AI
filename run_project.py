"""Rebuild the Olist warehouse and models, then serve the local dashboard."""

import os
from pathlib import Path
import shutil
import subprocess
import sys
import venv


ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"
VENV = ROOT / ".venv"

CHECK_DEPENDENCIES = """
from importlib.metadata import PackageNotFoundError, version
from sys import argv

for name in argv[1:]:
    try:
        version(name)
    except PackageNotFoundError:
        print(name)
"""


def main():
    npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
    if npm is None:
        print("Install Node.js with npm and make sure it is on PATH.", file=sys.stderr)
        return 1

    python = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    step = "Create the Python environment"
    try:
        if not python.is_file():
            print(f"\n== {step} ==", flush=True)
            venv.create(VENV, with_pip=True)

        step = "Check Python dependencies"
        requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
        packages = [line.split("==", 1)[0].strip() for line in requirements
                    if line.strip() and not line.lstrip().startswith("#")]
        missing = subprocess.run(
            [python, "-c", CHECK_DEPENDENCIES, *packages],
            cwd=ROOT, check=True, stdout=subprocess.PIPE, text=True,
        ).stdout.splitlines()
        if missing:
            step = "Install Python dependencies"
            print(f"\n== {step} ({', '.join(missing)}) ==", flush=True)
            pip_check = subprocess.run(
                [python, "-c", "from importlib.util import find_spec; raise SystemExit(find_spec('pip') is None)"],
                cwd=ROOT,
            )
            if pip_check.returncode:
                subprocess.run([python, "-m", "ensurepip"], cwd=ROOT, check=True)
            subprocess.run(
                [python, "-m", "pip", "install", "--disable-pip-version-check", "-r", "requirements.txt"],
                cwd=ROOT, check=True,
            )

        steps = []
        node_modules = WEB / "node_modules"
        if not all((node_modules / package / "package.json").is_file() for package in ("vite", "typescript")):
            steps.append(("Install web dependencies", [npm, "ci"], WEB))
        steps.extend([
            ("Build and validate the warehouse", [python, "etl.py"], ROOT),
            ("Train the delivery model", [python, "train_delivery.py"], ROOT),
            ("Segment customers", [python, "segment_customers.py"], ROOT),
            ("Export the dashboard data", [python, "web/export_snapshot.py"], ROOT),
            ("Build the web dashboard", [npm, "run", "build"], WEB),
            ("Start the dashboard and prediction API", [python, "web/predict_api.py"], ROOT),
        ])
        for step, command, directory in steps:
            print(f"\n== {step} ==", flush=True)
            subprocess.run(command, cwd=directory, check=True)
    except subprocess.CalledProcessError as error:
        print(f"{step} failed (exit code {error.returncode}).", file=sys.stderr)
        return 1
    except OSError as error:
        print(f"{step} failed: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
