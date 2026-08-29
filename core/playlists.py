import os
import unicodedata

from . import storage

MAX_PLAYLISTS = 25
MAX_SONGS = 500


def _path(guild_id: int) -> str:
    return os.path.join(storage.data_dir("playlists"), f"{guild_id}.json")


def _key(name: str) -> str:
    clean = unicodedata.normalize("NFKD", name.strip().lower())
    return "".join(c for c in clean if not unicodedata.combining(c))


def all_playlists(guild_id: int) -> dict:
    return storage.read_json(_path(guild_id), {})


def _write(guild_id: int, data: dict) -> bool:
    return storage.write_json(_path(guild_id), data)


def find(guild_id: int, name: str):
    target = _key(name)
    for real_name, data in all_playlists(guild_id).items():
        if _key(real_name) == target:
            return real_name, data
    return None, None


def create(guild_id: int, name: str, author: str) -> tuple[bool, str]:
    name = name.strip()[:60]
    if not name:
        return False, "El nombre no puede estar vacío."

    data = all_playlists(guild_id)
    if len(data) >= MAX_PLAYLISTS:
        return False, f"Ya hay {MAX_PLAYLISTS} playlists en este servidor, el máximo."
    if find(guild_id, name)[0]:
        return False, f"Ya existe una playlist llamada **{name}**."

    data[name] = {"created_by": author, "songs": []}
    if not _write(guild_id, data):
        return False, "No pude guardar la playlist en el disco."
    return True, f"Playlist **{name}** creada. Agrégale canciones con `/playlist agregar`."


def add(guild_id: int, name: str, song: dict) -> tuple[bool, str]:
    data = all_playlists(guild_id)
    real_name, playlist_data = find(guild_id, name)
    if not real_name:
        return False, f"No existe ninguna playlist llamada **{name}**."

    songs = playlist_data.setdefault("songs", [])
    if len(songs) >= MAX_SONGS:
        return False, f"**{real_name}** ya tiene {MAX_SONGS} canciones, el máximo."
    if any(c.get("url") == song.get("url") for c in songs):
        return False, f"**{song.get('title')}** ya está en **{real_name}**."

    songs.append(song)
    data[real_name] = playlist_data
    if not _write(guild_id, data):
        return False, "No pude guardar la playlist en el disco."
    return True, f"Agregada a **{real_name}**: {song.get('title')}  ({len(songs)} en total)"


def remove(guild_id: int, name: str, position: int) -> tuple[bool, str]:
    data = all_playlists(guild_id)
    real_name, playlist_data = find(guild_id, name)
    if not real_name:
        return False, f"No existe ninguna playlist llamada **{name}**."

    songs = playlist_data.get("songs", [])
    if not 1 <= position <= len(songs):
        return False, f"**{real_name}** tiene {len(songs)} canciones; elige entre 1 y {len(songs)}."

    removed = songs.pop(position - 1)
    data[real_name] = playlist_data
    if not _write(guild_id, data):
        return False, "No pude guardar la playlist en el disco."
    return True, f"Quitada de **{real_name}**: {removed.get('title')}"


def delete(guild_id: int, name: str) -> tuple[bool, str]:
    data = all_playlists(guild_id)
    real_name, _ = find(guild_id, name)
    if not real_name:
        return False, f"No existe ninguna playlist llamada **{name}**."

    del data[real_name]
    if not _write(guild_id, data):
        return False, "No pude guardar el cambio en el disco."
    return True, f"Playlist **{real_name}** borrada."


def names(guild_id: int) -> list[str]:
    return sorted(all_playlists(guild_id).keys(), key=_key)
