"""Run the Olist pipeline from a local control panel or the terminal."""

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import venv


ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"
VENV = ROOT / ".venv"
PYTHON = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")

STAGES = (
    ("warehouse", "Build and validate the warehouse", "etl.py"),
    ("delivery", "Train the delivery model", "train_delivery.py"),
    ("segments", "Segment customers", "segment_customers.py"),
    ("snapshot", "Export the dashboard data", "web/export_snapshot.py"),
    ("build", "Build the web dashboard", None),
    ("dashboard", "Start the dashboard and prediction API", "web/predict_api.py"),
)

CHECK_DEPENDENCIES = """
from importlib.metadata import PackageNotFoundError, version
from sys import argv

for name in argv[1:]:
    try:
        version(name)
    except PackageNotFoundError:
        print(name)
"""


def prepare_python(run, log):
    if not PYTHON.is_file():
        log("Creating the Python environment...")
        venv.create(VENV, with_pip=True)
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
    packages = [line.split("==", 1)[0].strip() for line in requirements
                if line.strip() and not line.lstrip().startswith("#")]
    missing = subprocess.run(
        [PYTHON, "-c", CHECK_DEPENDENCIES, *packages],
        cwd=ROOT, check=True, stdout=subprocess.PIPE, text=True,
    ).stdout.splitlines()
    if missing:
        log(f"Installing missing Python dependencies: {', '.join(missing)}")
        pip_check = subprocess.run(
            [
                PYTHON,
                "-c",
                "from importlib.util import find_spec; raise SystemExit(find_spec('pip') is None)"
            ],
            cwd=ROOT,
        )
        if pip_check.returncode:
            run([PYTHON, "-m", "ensurepip"], ROOT)
        run(
            [PYTHON, "-m", "pip", "install", "--disable-pip-version-check", "-r", "requirements.txt"],
            ROOT
        )


def command_for(stage, run, log):
    _, _, script = stage
    if script is not None:
        prepare_python(run, log)
        return [PYTHON, "-u", script], ROOT

    npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
    if npm is None:
        raise RuntimeError("Install Node.js with npm and make sure it is on PATH.")
    node_modules = WEB / "node_modules"
    if not all((node_modules / package / "package.json").is_file() for package in ("vite", "typescript")):
        log("Installing missing web dependencies...")
        run([npm, "ci"], WEB)
    return [npm, "run", "build"], WEB


def run_all():
    def run(command, directory):
        subprocess.run(command, cwd=directory, check=True)

    try:
        for stage in STAGES:
            _, title, _ = stage
            print(f"\n== {title} ==", flush=True)
            command, directory = command_for(stage, run, lambda line: print(line, flush=True))
            run(command, directory)
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"{title} failed: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--all", action="store_true", help="Run all stages in the terminal.")
    args = parser.parse_args()
    if args.all:
        return run_all()

    from pipeline_ui.server import serve

    return serve(STAGES, command_for)


if __name__ == "__main__":
    sys.exit(main())
