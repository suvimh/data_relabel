#!/usr/bin/env python3
"""Launch script - runs backend and frontend servers."""

import subprocess
import sys
import os
import signal

ROOT = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.join(ROOT, 'backend')
FRONTEND_DIR = os.path.join(ROOT, 'frontend')

processes = []


def _backend_python_works(py):
    result = subprocess.run(
        [py, "-c", "import numpy; import librosa; from numba import jit; print(numpy.__version__)"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    return result.returncode == 0, result.stdout.strip(), result.stderr.strip()


def resolve_backend_python():
    candidates = [sys.executable]
    framework_py = "/Library/Frameworks/Python.framework/Versions/3.12/bin/python3"
    if os.path.isfile(framework_py) and framework_py not in candidates:
        candidates.append(framework_py)
    env_py = os.environ.get("LABEL_PYTHON")
    if env_py and env_py not in candidates:
        candidates.insert(0, env_py)

    for py in candidates:
        ok, _, _ = _backend_python_works(py)
        if ok:
            return py

    print("ERROR: No Python environment can load librosa/numba.")
    print("Fix: pip install 'numpy<2.5'  OR  set LABEL_PYTHON to a working interpreter.")
    sys.exit(1)

def cleanup(signum=None, frame=None):
    for p in processes:
        p.terminate()
    sys.exit(0)

signal.signal(signal.SIGINT, cleanup)
signal.signal(signal.SIGTERM, cleanup)

print("Starting backend...")
backend_python = resolve_backend_python()
print(f"Using backend Python: {backend_python}")
p1 = subprocess.Popen(
    [backend_python, '-m', 'uvicorn', 'main:app', '--host', '127.0.0.1', '--port', '8000', '--reload'],
    cwd=BACKEND_DIR,
)
processes.append(p1)

print("Starting frontend...")
p2 = subprocess.Popen(
    ['npx', 'vite', '--host', '127.0.0.1'],
    cwd=FRONTEND_DIR,
)
processes.append(p2)

print("\nBackend:  http://127.0.0.1:8000")
print("Frontend: http://127.0.0.1:5173")
print("Press Ctrl+C to stop both servers.\n")

try:
    p1.wait()
except KeyboardInterrupt:
    cleanup()
