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
from typing import Optional

from . import storage


def _ruta(guild_id: int) -> str:
    return os.path.join(storage.carpeta("stats"), f"{guild_id}.json")


# Las personas se guardan por ID de Discord, no por apodo: así quien se
# cambia el nombre en el servidor sigue siendo la misma en el ranking.
# Las entradas viejas, de cuando se guardaba por nombre, quedan con este
# prefijo hasta que esa persona vuelva a poner música y se fusionen.
PREFIJO_SIN_ID = "nombre:"
_LEGADO_AUTOPLAY = "Autoplay"


def _normalizar_usuarios(datos: dict) -> dict:
    """Lleva el formato viejo {apodo: veces} al nuevo {id: {nombre, veces}}.

    De paso tira la entrada 'Autoplay': la radio no es una persona y no
    tiene por qué competir en el ranking de quién pone más música."""
    usuarios = datos.get("usuarios", {})
    convertidos = {}
    for clave, valor in usuarios.items():
        if isinstance(valor, dict):
            convertidos[clave] = valor
        elif clave != _LEGADO_AUTOPLAY:
            convertidos[f"{PREFIJO_SIN_ID}{clave}"] = {"nombre": clave, "veces": valor}
    datos["usuarios"] = convertidos
    return convertidos


def registrar(guild_id: int, titulo: str, url: str, pedida_por: str,
              usuario_id: Optional[int] = None) -> None:
    """Suma una reproducción. Si falla, se ignora: nunca vale la pena
    romper la música por no poder escribir una estadística.

    La canción siempre cuenta, la haya puesto alguien o la radio. La
    persona solo cuenta si hay `usuario_id`, que es justo lo que distingue
    a la radio (no tiene) de alguien de carne y hueso."""
    try:
        datos = storage.leer(_ruta(guild_id), {})

        canciones = datos.setdefault("canciones", {})
        entrada = canciones.setdefault(url, {"titulo": titulo, "veces": 0})
        entrada["titulo"] = titulo          # por si cambió el título
        entrada["veces"] = entrada.get("veces", 0) + 1
        entrada["ultima"] = int(time.time())

        usuarios = _normalizar_usuarios(datos)
        if usuario_id is not None:
            clave = str(usuario_id)
            persona = usuarios.get(clave)
            if persona is None:
                # ¿Quedó una entrada vieja sin id con este mismo apodo? La
                # absorbemos para no perder lo que ya llevaba contado.
                anterior = usuarios.pop(f"{PREFIJO_SIN_ID}{pedida_por}", None)
                persona = {"nombre": pedida_por,
                           "veces": anterior.get("veces", 0) if anterior else 0}
                usuarios[clave] = persona
            persona["nombre"] = pedida_por      # por si se cambió el apodo
            persona["veces"] = persona.get("veces", 0) + 1

        storage.guardar(_ruta(guild_id), datos)
    except Exception:
        pass


# Cuántas veces tiene que haber sonado una canción para entrar al ranking.
# En un servidor donde se pone mucha música, sin este mínimo el top se
# llena de cosas que sonaron una sola vez y no dice nada de lo que
# realmente se escucha. El ranking de personas no lo usa: ahí interesa
# cuántas canciones pidió cada quien, se repitan o no.
MINIMO_REPETICIONES = 3


def top_canciones(guild_id: int, limite: int = 10,
                  minimo: int = MINIMO_REPETICIONES) -> list[dict]:
    canciones = storage.leer(_ruta(guild_id), {}).get("canciones", {})
    ordenadas = sorted(
        ({"url": url, **info} for url, info in canciones.items()
         if info.get("veces", 0) >= minimo),
        key=lambda c: c.get("veces", 0),
        reverse=True,
    )
    return ordenadas[:limite]


def top_usuarios(guild_id: int, limite: int = 10) -> list[tuple[str, int]]:
    usuarios = _normalizar_usuarios(storage.leer(_ruta(guild_id), {}))
    filas = [(p.get("nombre", "?"), p.get("veces", 0)) for p in usuarios.values()]
    return sorted(filas, key=lambda u: u[1], reverse=True)[:limite]


def totales(guild_id: int) -> tuple[int, int]:
    """(reproducciones totales, canciones distintas)"""
    canciones = storage.leer(_ruta(guild_id), {}).get("canciones", {})
    return sum(c.get("veces", 0) for c in canciones.values()), len(canciones)
