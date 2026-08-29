# -*- coding: utf-8 -*-
"""Playlists con nombre, compartidas por servidor.

Se guardan en playlists/<guild_id>.json:

    {
      "chill": {
        "creada_por": "Niku",
        "canciones": [{"titulo": "...", "url": "...", "duracion": 210}]
      }
    }

Son distintas de los favoritos, que son de cada usuario y viven en
favorites/<user_id>.txt.
"""
import os
import unicodedata

from . import almacen

MAX_PLAYLISTS = 25          # el select de Discord no muestra más de 25
MAX_CANCIONES = 500


def _ruta(guild_id: int) -> str:
    return os.path.join(almacen.carpeta("playlists"), f"{guild_id}.json")


def _clave(nombre: str) -> str:
    """Normaliza el nombre para buscar: 'Chill ✿' y 'chill' son la misma."""
    limpio = unicodedata.normalize("NFKD", nombre.strip().lower())
    return "".join(c for c in limpio if not unicodedata.combining(c))


def todas(guild_id: int) -> dict:
    return almacen.leer(_ruta(guild_id), {})


def _guardar(guild_id: int, datos: dict) -> bool:
    return almacen.guardar(_ruta(guild_id), datos)


def buscar(guild_id: int, nombre: str):
    """Devuelve (nombre_real, playlist) o (None, None)."""
    objetivo = _clave(nombre)
    for real, datos in todas(guild_id).items():
        if _clave(real) == objetivo:
            return real, datos
    return None, None


def crear(guild_id: int, nombre: str, autor: str) -> tuple[bool, str]:
    nombre = nombre.strip()[:60]
    if not nombre:
        return False, "El nombre no puede estar vacío."

    datos = todas(guild_id)
    if len(datos) >= MAX_PLAYLISTS:
        return False, f"Ya hay {MAX_PLAYLISTS} playlists en este servidor, el máximo."
    if buscar(guild_id, nombre)[0]:
        return False, f"Ya existe una playlist llamada **{nombre}**."

    datos[nombre] = {"creada_por": autor, "canciones": []}
    if not _guardar(guild_id, datos):
        return False, "No pude guardar la playlist en el disco."
    return True, f"Playlist **{nombre}** creada. Agrégale canciones con `/playlist agregar`."


def agregar(guild_id: int, nombre: str, cancion: dict) -> tuple[bool, str]:
    datos = todas(guild_id)
    real, lista = buscar(guild_id, nombre)
    if not real:
        return False, f"No existe ninguna playlist llamada **{nombre}**."

    canciones = lista.setdefault("canciones", [])
    if len(canciones) >= MAX_CANCIONES:
        return False, f"**{real}** ya tiene {MAX_CANCIONES} canciones, el máximo."
    if any(c.get("url") == cancion.get("url") for c in canciones):
        return False, f"**{cancion.get('titulo')}** ya está en **{real}**."

    canciones.append(cancion)
    datos[real] = lista
    if not _guardar(guild_id, datos):
        return False, "No pude guardar la playlist en el disco."
    return True, f"Agregada a **{real}**: {cancion.get('titulo')}  ({len(canciones)} en total)"


def quitar(guild_id: int, nombre: str, posicion: int) -> tuple[bool, str]:
    datos = todas(guild_id)
    real, lista = buscar(guild_id, nombre)
    if not real:
        return False, f"No existe ninguna playlist llamada **{nombre}**."

    canciones = lista.get("canciones", [])
    if not 1 <= posicion <= len(canciones):
        return False, f"**{real}** tiene {len(canciones)} canciones; elige entre 1 y {len(canciones)}."

    quitada = canciones.pop(posicion - 1)
    datos[real] = lista
    if not _guardar(guild_id, datos):
        return False, "No pude guardar la playlist en el disco."
    return True, f"Quitada de **{real}**: {quitada.get('titulo')}"


def borrar(guild_id: int, nombre: str) -> tuple[bool, str]:
    datos = todas(guild_id)
    real, _ = buscar(guild_id, nombre)
    if not real:
        return False, f"No existe ninguna playlist llamada **{nombre}**."

    del datos[real]
    if not _guardar(guild_id, datos):
        return False, "No pude guardar el cambio en el disco."
    return True, f"Playlist **{real}** borrada."


def nombres(guild_id: int) -> list[str]:
    return sorted(todas(guild_id).keys(), key=_clave)
