# -*- coding: utf-8 -*-
"""Arma chiwiro.ico a partir del icono de Cinnamoroll.

El .ico original trae un solo tamaño (100x100), y Windows necesita varios
para que se vea nítido en la barra de tareas, el escritorio y alt-tab.
Este script genera todos los tamaños de una sola imagen.

Uso:  venv\\Scripts\\python.exe herramientas\\generar_icono.py
"""
import os

from PIL import Image

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ORIGEN = os.path.join(BASE, "icons8-rollo-de-canela-100.ico")
SALIDA = os.path.join(BASE, "chiwiro.ico")

TAMANOS = [16, 20, 24, 32, 40, 48, 64, 96, 128, 256]


def main():
    imagen = Image.open(ORIGEN).convert("RGBA")
    print(f"Origen: {os.path.basename(ORIGEN)} {imagen.size[0]}x{imagen.size[1]}")

    # Escalamos primero al tamaño más grande: así los intermedios salen de una
    # imagen suavizada y no de la de 100px directamente.
    grande = imagen.resize((max(TAMANOS), max(TAMANOS)), Image.LANCZOS)
    grande.save(SALIDA, format="ICO", sizes=[(t, t) for t in TAMANOS])

    print(f"Tamaños: {', '.join(str(t) for t in TAMANOS)}")
    print(f"Listo: {SALIDA} ({os.path.getsize(SALIDA) / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
