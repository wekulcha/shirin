"""HMAC initData verification, derived from Market; official Telegram scheme."""

import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl


def verify_telegram_init_data(init_data: str, bot_token: str, max_age: int = 3600) -> dict | None:
    try:
        if not init_data or not bot_token or len(init_data) > 16384:
            return None
        pairs = parse_qsl(init_data, keep_blank_values=True, strict_parsing=True)
        if len(pairs) != len(dict(pairs)):
            return None
        values = dict(pairs)
        received = values.pop("hash")
        timestamp = int(values["auth_date"])
        if timestamp > time.time() + 30 or time.time() - timestamp > max_age:
            return None
        secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
        expected = hmac.new(secret, "\n".join(f"{k}={v}" for k, v in sorted(values.items())).encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, received):
            return None
        user = json.loads(values["user"])
        if not isinstance(user.get("id"), int) or isinstance(user["id"], bool) or user["id"] <= 0:
            return None
        return user
    except (ValueError, KeyError, TypeError):
        return None
