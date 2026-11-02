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

def cleanup(signum=None, frame=None):
    for p in processes:
        p.terminate()
    sys.exit(0)

signal.signal(signal.SIGINT, cleanup)
signal.signal(signal.SIGTERM, cleanup)

print("Starting backend...")
p1 = subprocess.Popen(
    [sys.executable, '-m', 'uvicorn', 'main:app', '--host', '127.0.0.1', '--port', '8000', '--reload'],
    cwd=BACKEND_DIR,
)
processes.append(p1)

print("Starting frontend...")
p2 = subprocess.Popen(
    ['node', os.path.join(FRONTEND_DIR, 'node_modules', 'vite', 'bin', 'vite.js'), '--host', '127.0.0.1'],
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
