"""Local demo runner. Ctrl+C stops only the three processes started here."""

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

root = Path(__file__).resolve().parents[1]
subprocess.run([sys.executable, str(root / "scripts/demo.py")], check=True)
commands = [
    ([sys.executable, "-m", "uvicorn", "app.main:app", "--port", "8083", "--reload", "--no-access-log"], root / "backend"),
    (["npm", "run", "dev"], root / "user_panel"),
    (["npm", "run", "dev"], root / "admin_panel"),
]
processes = []
try:
    for command, cwd in commands:
        processes.append(subprocess.Popen(command, cwd=cwd, start_new_session=True))
    while all(p.poll() is None for p in processes):
        time.sleep(1)
except KeyboardInterrupt:
    pass
finally:
    for process in processes:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
    for process in processes:
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
