"""Start/check the Market integration using only synthetic isolated settings."""

import os
import sys
from pathlib import Path

from dotenv import dotenv_values

root = Path(__file__).resolve().parents[1]
env = dotenv_values(root / ".env")
if env.get("SHIRIN_ENVIRONMENT") != "development" or env.get("SHIRIN_WORK_GROUP_ID") != "0":
    raise SystemExit("Requires isolated Shirin demo; run scripts/demo.py first")
market = root.parent / "market-shirin-integration/backend"
os.environ.update(
    {
        "MARKET_DATABASE_URL": "sqlite+aiosqlite:////private/tmp/shirin-market-smoke.db",
        "MARKET_SUPERADMIN_ALLOWED_IDS": "101",
        "MARKET_SUPERADMIN_BOT_TOKEN": "654321:synthetic-market-bot-secret",
        "MARKET_USER_BOT_TOKEN": "",
        "MARKET_ADMIN_BOT_TOKEN": "",
        "MARKET_AUTH_ACCESS_SECRET": "synthetic-market-auth-secret-independent",
        "MARKET_SHIRIN_API_BASE": "http://127.0.0.1:8083/shirin/api",
        "MARKET_SHIRIN_INTEGRATION_SECRET": env["SHIRIN_MARKET_INTEGRATION_SECRET"],
        "PYTHONPATH": str(market),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
)
os.chdir(market)
args = (
    [str(root / "scripts/market-smoke.py")]
    if "--check" in sys.argv
    else ["-m", "uvicorn", "app.main:app", "--port", "8085", "--no-access-log"]
)
os.execv(sys.executable, [sys.executable, *args])
