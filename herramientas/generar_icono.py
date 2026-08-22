# -*- coding: utf-8 -*-
"""Genera chiwiro.ico sin dependencias externas (nada de Pillow).

Dibuja un cuadrado redondeado en color Discord con una nota musical blanca,
en todos los tamaños que Windows usa (barra de tareas, escritorio, alt-tab).
Se ejecuta una sola vez; si quieres cambiar el diseño, ajusta COLOR_FONDO o
las coordenadas de la nota y vuelve a ejecutarlo.
"""
import os
import struct

SALIDA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "chiwiro.ico")

COLOR_FONDO = (88, 101, 242)      # blurple de Discord (R, G, B)
COLOR_NOTA = (255, 255, 255)
TAMANOS = [16, 24, 32, 48, 64, 128, 256]
SUPERMUESTREO = 4                  # suavizado de bordes


def _dentro_cuadrado_redondeado(x, y, radio=0.23):
    """x, y normalizados de 0 a 1."""
    dx = min(x, 1.0 - x)
    dy = min(y, 1.0 - y)
    if dx >= radio or dy >= radio:
        return 0.0 <= x <= 1.0 and 0.0 <= y <= 1.0
    # Estamos en una esquina: hay que medir contra el arco.
    cx = radio if x < 0.5 else 1.0 - radio
    cy = radio if y < 0.5 else 1.0 - radio
    return ((x - cx) ** 2 + (y - cy) ** 2) <= radio ** 2


def _dentro_elipse(x, y, cx, cy, rx, ry):
    return ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2 <= 1.0


def _dentro_rect(x, y, x0, y0, x1, y1):
    return x0 <= x <= x1 and y0 <= y <= y1


def _dentro_barra(x, y):
    """La barra inclinada que une las dos plicas de la nota doble."""
    x0, x1 = 0.405, 0.782
    if not (x0 <= x <= x1):
        return False
    t = (x - x0) / (x1 - x0)
    tope = 0.245 + t * (0.170 - 0.245)
    return tope <= y <= tope + 0.105


def _dentro_nota(x, y):
    # Cabezas
    if _dentro_elipse(x, y, 0.330, 0.715, 0.120, 0.093):
        return True
    if _dentro_elipse(x, y, 0.652, 0.645, 0.120, 0.093):
        return True
    # Plicas
    if _dentro_rect(x, y, 0.405, 0.245, 0.450, 0.715):
        return True
    if _dentro_rect(x, y, 0.727, 0.170, 0.772, 0.645):
        return True
    # Barra
    return _dentro_barra(x, y)


def _render(lado):
    """Devuelve los píxeles BGRA, de abajo hacia arriba (como pide el BMP)."""
    ss = SUPERMUESTREO if lado <= 128 else 3
    total = ss * ss
    filas = []
    for py in range(lado):
        fila = bytearray()
        for px in range(lado):
            muestras_fondo = 0
            muestras_nota = 0
            for sy in range(ss):
                for sx in range(ss):
                    x = (px + (sx + 0.5) / ss) / lado
                    y = (py + (sy + 0.5) / ss) / lado
                    if not _dentro_cuadrado_redondeado(x, y):
                        continue
                    muestras_fondo += 1
                    if _dentro_nota(x, y):
                        muestras_nota += 1

            if muestras_fondo == 0:
                fila += b"\x00\x00\x00\x00"
                continue

            alfa = muestras_fondo / total
            mezcla = muestras_nota / muestras_fondo
            r = round(COLOR_FONDO[0] + (COLOR_NOTA[0] - COLOR_FONDO[0]) * mezcla)
            g = round(COLOR_FONDO[1] + (COLOR_NOTA[1] - COLOR_FONDO[1]) * mezcla)
            b = round(COLOR_FONDO[2] + (COLOR_NOTA[2] - COLOR_FONDO[2]) * mezcla)
            # BMP guarda el color premultiplicado por nada, pero sí en orden BGRA.
            fila += bytes((b, g, r, round(alfa * 255)))
        filas.append(bytes(fila))
    return b"".join(reversed(filas))


def _imagen_ico(lado):
    """Un PNG-menos: DIB de 32 bits con su máscara AND vacía."""
    pixeles = _render(lado)
    cabecera = struct.pack(
        "<IiiHHIIiiII",
        40,            # tamaño de la cabecera
        lado,          # ancho
        lado * 2,      # alto (XOR + AND, como exige el formato ICO)
        1,             # planos
        32,            # bits por píxel
        0,             # sin compresión
        len(pixeles),
        0, 0, 0, 0,
    )
    fila_mascara = ((lado + 31) // 32) * 4      # cada fila alineada a 4 bytes
    mascara = b"\x00" * (fila_mascara * lado)
    return cabecera + pixeles + mascara


def main():
    imagenes = []
    for lado in TAMANOS:
        print(f"  dibujando {lado}x{lado}...")
        imagenes.append((lado, _imagen_ico(lado)))

    cabecera = struct.pack("<HHH", 0, 1, len(imagenes))
    desplazamiento = 6 + 16 * len(imagenes)
    entradas = b""
    cuerpo = b""
    for lado, datos in imagenes:
        entradas += struct.pack(
            "<BBBBHHII",
            0 if lado >= 256 else lado,   # 0 significa 256
            0 if lado >= 256 else lado,
            0, 0, 1, 32,
            len(datos),
            desplazamiento,
        )
        cuerpo += datos
        desplazamiento += len(datos)

    with open(SALIDA, "wb") as f:
        f.write(cabecera + entradas + cuerpo)
    print(f"\nListo: {SALIDA} ({os.path.getsize(SALIDA) / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
