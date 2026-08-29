# -*- coding: utf-8 -*-
"""Cuenta qué se escucha en cada servidor.

Se guarda en stats/<guild_id>.json:

    {
      "canciones": {"<url>": {"titulo": "...", "veces": 12, "ultima": 1756...}},
      "usuarios":  {"Niku": 34}
    }

Ojo: esto NO es el historial de la sesión ni la cola. Es solo un contador
para /top; el bot no restaura nada al arrancar.
"""
import os
import time

from . import storage


def _ruta(guild_id: int) -> str:
    return os.path.join(storage.carpeta("stats"), f"{guild_id}.json")


def registrar(guild_id: int, titulo: str, url: str, pedida_por: str) -> None:
    """Suma una reproducción. Si falla, se ignora: nunca vale la pena
    romper la música por no poder escribir una estadística."""
    try:
        datos = storage.leer(_ruta(guild_id), {})
        canciones = datos.setdefault("canciones", {})
        entrada = canciones.setdefault(url, {"titulo": titulo, "veces": 0})
        entrada["titulo"] = titulo          # por si cambió el título
        entrada["veces"] = entrada.get("veces", 0) + 1
        entrada["ultima"] = int(time.time())

        usuarios = datos.setdefault("usuarios", {})
        usuarios[pedida_por] = usuarios.get(pedida_por, 0) + 1

        storage.guardar(_ruta(guild_id), datos)
    except Exception:
        pass


def top_canciones(guild_id: int, limite: int = 10) -> list[dict]:
    canciones = storage.leer(_ruta(guild_id), {}).get("canciones", {})
    ordenadas = sorted(
        ({"url": url, **info} for url, info in canciones.items()),
        key=lambda c: c.get("veces", 0),
        reverse=True,
    )
    return ordenadas[:limite]


def top_usuarios(guild_id: int, limite: int = 10) -> list[tuple[str, int]]:
    usuarios = storage.leer(_ruta(guild_id), {}).get("usuarios", {})
    return sorted(usuarios.items(), key=lambda u: u[1], reverse=True)[:limite]


def totales(guild_id: int) -> tuple[int, int]:
    """(reproducciones totales, canciones distintas)"""
    canciones = storage.leer(_ruta(guild_id), {}).get("canciones", {})
    return sum(c.get("veces", 0) for c in canciones.values()), len(canciones)
