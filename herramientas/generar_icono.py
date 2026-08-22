# -*- coding: utf-8 -*-
"""Arma chiwiro.ico a partir del icono de Cinnamoroll.

El .ico original trae un solo tamaño (100x100) y Windows necesita varios
para verse nítido en la barra de tareas, el escritorio y alt-tab.

Dos detalles que importan y por eso no usamos el guardado de ICO de Pillow:

1. Cada tamaño se escala DIRECTO desde el original. Generar un 256 y de ahí
   bajar a 32 (100 -> 256 -> 32) deja borrosos justo los tamaños chicos, que
   son los que más se ven.
2. El `append_images` de Pillow no arma multi-tamaño en ICO: guarda uno solo.
   Escribimos el archivo a mano, que el formato es simple.

Uso:  venv\\Scripts\\python.exe herramientas\\generar_icono.py
"""
import os
import struct

from PIL import Image

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ORIGEN = os.path.join(BASE, "icons8-rollo-de-canela-100.ico")
SALIDA = os.path.join(BASE, "chiwiro.ico")

TAMANOS = [16, 20, 24, 32, 40, 48, 64, 96, 128, 256]


def _dib(imagen: Image.Image) -> bytes:
    """Convierte la imagen en un DIB de 32 bits, que es lo que espera un ICO:
    cabecera, píxeles BGRA de abajo hacia arriba, y una máscara AND vacía."""
    lado = imagen.size[0]
    pixeles = bytearray()
    for y in range(lado - 1, -1, -1):          # el BMP va de abajo hacia arriba
        for x in range(lado):
            r, g, b, a = imagen.getpixel((x, y))
            pixeles += bytes((b, g, r, a))

    cabecera = struct.pack(
        "<IiiHHIIiiII",
        40,              # tamaño de la cabecera
        lado,            # ancho
        lado * 2,        # alto (XOR + AND, como exige el formato)
        1, 32, 0,        # planos, bits por píxel, sin compresión
        len(pixeles),
        0, 0, 0, 0,
    )
    fila_mascara = ((lado + 31) // 32) * 4     # cada fila alineada a 4 bytes
    return cabecera + bytes(pixeles) + b"\x00" * (fila_mascara * lado)


def _recortar(imagen: Image.Image, margen=0.0) -> Image.Image:
    """Saca el margen transparente y deja la carita centrada en un cuadrado.

    El icono original tiene bastante aire alrededor: al escalar a 16px, ese
    aire se come la mitad de los píxeles útiles y la cara queda irreconocible.
    Recortando, cada tamaño chico aprovecha todo el cuadro."""
    caja = imagen.getbbox()
    if not caja:
        return imagen
    recorte = imagen.crop(caja)

    lado = int(max(recorte.size) * (1 + margen * 2))
    cuadro = Image.new("RGBA", (lado, lado), (0, 0, 0, 0))
    cuadro.alpha_composite(recorte, ((lado - recorte.size[0]) // 2,
                                     (lado - recorte.size[1]) // 2))
    return cuadro


def main():
    original = Image.open(ORIGEN).convert("RGBA")
    print(f"Origen: {os.path.basename(ORIGEN)} {original.size[0]}x{original.size[1]}")
    original = _recortar(original)
    print(f"Recortado a: {original.size[0]}x{original.size[1]} (sin margen transparente)")

    imagenes = []
    for lado in TAMANOS:
        capa = original.resize((lado, lado), Image.LANCZOS)
        imagenes.append((lado, _dib(capa)))

    cabecera = struct.pack("<HHH", 0, 1, len(imagenes))
    desplazamiento = 6 + 16 * len(imagenes)
    entradas = b""
    cuerpo = b""
    for lado, datos in imagenes:
        entradas += struct.pack(
            "<BBBBHHII",
            0 if lado >= 256 else lado,        # 0 significa 256
            0 if lado >= 256 else lado,
            0, 0, 1, 32,
            len(datos),
            desplazamiento,
        )
        cuerpo += datos
        desplazamiento += len(datos)

    with open(SALIDA, "wb") as f:
        f.write(cabecera + entradas + cuerpo)

    print(f"Tamaños: {', '.join(str(t) for t in TAMANOS)}")
    print(f"Listo: {SALIDA} ({os.path.getsize(SALIDA) / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
