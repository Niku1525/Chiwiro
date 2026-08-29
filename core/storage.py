# -*- coding: utf-8 -*-
"""Lectura y escritura de los JSON del bot, con candado y escritura atómica.

Lo usan playlists y estadísticas. La escritura va primero a un archivo
temporal y después se renombra: si se corta la luz a mitad de guardar, el
archivo viejo queda intacto en vez de quedar a medias.
"""
import json
import os
import threading

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_candado = threading.Lock()


def carpeta(nombre: str) -> str:
    """Carpeta de datos del bot. Todo lo que se genera en tiempo de
    ejecución vive bajo data/, para no ensuciar la raíz del proyecto."""
    ruta = os.path.join(RAIZ, "data", nombre)
    os.makedirs(ruta, exist_ok=True)
    return ruta


def leer(ruta: str, por_defecto=None):
    try:
        with open(ruta, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {} if por_defecto is None else por_defecto


def guardar(ruta: str, datos) -> bool:
    temporal = ruta + ".tmp"
    with _candado:
        try:
            with open(temporal, "w", encoding="utf-8") as f:
                json.dump(datos, f, ensure_ascii=False, indent=2)
            os.replace(temporal, ruta)
            return True
        except OSError:
            try:
                os.remove(temporal)
            except OSError:
                pass
            return False
