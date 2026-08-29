import os
import time
from typing import Optional

from . import storage


def _path(guild_id: int) -> str:
    return os.path.join(storage.data_dir("stats"), f"{guild_id}.json")


NO_ID_PREFIX = "name:"
_LEGACY_AUTOPLAY = "Autoplay"


def _normalize_users(data: dict) -> dict:
    users = data.get("users", {})
    converted = {}
    for user_key, value in users.items():
        if isinstance(value, dict):
            converted[user_key] = value
        elif user_key != _LEGACY_AUTOPLAY:
            converted[f"{NO_ID_PREFIX}{user_key}"] = {"name": user_key, "plays": value}
    data["users"] = converted
    return converted


def record(guild_id: int, title: str, url: str, requested_by: str,
           user_id: Optional[int] = None) -> None:
    try:
        data = storage.read_json(_path(guild_id), {})

        songs = data.setdefault("songs", {})
        entry = songs.setdefault(url, {"title": title, "plays": 0})
        entry["title"] = title
        entry["plays"] = entry.get("plays", 0) + 1
        entry["last"] = int(time.time())

        users = _normalize_users(data)
        if user_id is not None:
            user_key = str(user_id)
            person = users.get(user_key)
            if person is None:
                previous = users.pop(f"{NO_ID_PREFIX}{requested_by}", None)
                person = {"name": requested_by,
                          "plays": previous.get("plays", 0) if previous else 0}
                users[user_key] = person
            person["name"] = requested_by
            person["plays"] = person.get("plays", 0) + 1

        storage.write_json(_path(guild_id), data)
    except Exception:
        pass


MIN_PLAYS = 3


def top_songs(guild_id: int, limit: int = 10,
              minimum: int = MIN_PLAYS) -> list[dict]:
    songs = storage.read_json(_path(guild_id), {}).get("songs", {})
    ordered = sorted(
        ({"url": url, **info} for url, info in songs.items()
         if info.get("plays", 0) >= minimum),
        key=lambda c: c.get("plays", 0),
        reverse=True,
    )
    return ordered[:limit]


def top_users(guild_id: int, limit: int = 10) -> list[tuple[str, int]]:
    users = _normalize_users(storage.read_json(_path(guild_id), {}))
    rows = [(p.get("name", "?"), p.get("plays", 0)) for p in users.values()]
    return sorted(rows, key=lambda u: u[1], reverse=True)[:limit]


def totals(guild_id: int) -> tuple[int, int]:
    songs = storage.read_json(_path(guild_id), {}).get("songs", {})
    return sum(c.get("plays", 0) for c in songs.values()), len(songs)
