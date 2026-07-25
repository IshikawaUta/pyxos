import json
import time
from pathlib import Path

CACHE_DIR = Path.home() / ".pyxos"
CACHE_FILE = CACHE_DIR / "cache.json"


def save_cache(projects):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    data = {
        "cached_at": time.time(),
        "projects": projects,
    }

    def default_serializer(obj):
        from datetime import datetime
        if isinstance(obj, datetime):
            return obj.isoformat()
        from bson import ObjectId
        if isinstance(obj, ObjectId):
            return str(obj)
        raise TypeError(f"Type {type(obj)} not serializable")

    with open(CACHE_FILE, "w") as f:
        json.dump(data, f, indent=2, default=default_serializer)


def load_cache(max_age_seconds=3600):
    if not CACHE_FILE.exists():
        return None

    try:
        with open(CACHE_FILE) as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None

    cached_at = data.get("cached_at", 0)
    if time.time() - cached_at > max_age_seconds:
        return None

    return data.get("projects", [])


def invalidate_cache():
    if CACHE_FILE.exists():
        CACHE_FILE.unlink()
        return True
    return False
