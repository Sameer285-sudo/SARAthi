"""
Launch all PDS360 microservices in separate processes.

Usage:
    cd services
    python start_all.py

Services:
    8000 — Auth
    8001 — Overview
    8002 — SMARTAllot
    8003 — Anomalies
    8004 — PDSAIBot
    8005 — Call Centre
"""
import subprocess
import sys
import time
from pathlib import Path

SERVICES = [
    ("Auth",        "auth_service/main.py", 8000),
    ("Overview",    "overview/main.py",    8001),
    ("SMARTAllot",  "smart_allot/main.py", 8002),
    ("Anomalies",   "anomalies/main.py",   8003),
    ("PDSAIBot",    "pdsaibot/main.py",    8004),
    ("Call Centre", "call_centre/main.py", 8005),
]

BASE = Path(__file__).parent


def main():
    procs = []
    for name, path, port in SERVICES:
        cmd = [sys.executable, str(BASE / path)]
        p = subprocess.Popen(cmd)
        procs.append((name, port, p))
        print(f"  Started {name:<14} -> http://localhost:{port}  (PID {p.pid})")
        time.sleep(0.3)

    print()
    print("All services started. Swagger docs:")
    for name, port, _ in procs:
        print(f"  {name:<14} -> http://localhost:{port}/docs")
    print()
    print("Press Ctrl+C to stop all services.")

    try:
        for _, _, p in procs:
            p.wait()
    except KeyboardInterrupt:
        print("\nShutting down...")
        for _, _, p in procs:
            p.terminate()
        for _, _, p in procs:
            p.wait()
        print("All services stopped.")


if __name__ == "__main__":
    main()
