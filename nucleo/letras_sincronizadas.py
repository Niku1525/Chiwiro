# -*- coding: utf-8 -*-
"""Letras con marcas de tiempo, para el modo karaoke.

Genius (que ya usa el bot para /lyrics) da la letra en texto plano, sin
tiempos. Para saber qué verso suena en cada segundo hace falta otra fuente:
lrclib.net, que es gratis, no pide API key y devuelve formato LRC:

    [00:23.62] Ella durmió al calor de las masas

Si una canción no tiene versión sincronizada, se avisa y el usuario se
queda con /lyrics, que sigue funcionando igual.
"""
import logging
import re

import requests

log = logging.getLogger(__name__)

API = "https://lrclib.net/api/search"
AGENTE = "ChiwiroMusicBot/1.0 (bot de Discord de uso personal)"

# [mm:ss.xx] texto   —  los centésimos son opcionales
_LINEA_LRC = re.compile(r"\[(\d{1,3}):(\d{2})(?:[.:](\d{1,3}))?\]\s*(.*)")

# Cuánto puede diferir la duración de lrclib de la del video de YouTube
# para seguir considerándolo la misma grabación.
TOLERANCIA_DURACION = 12


def _parsear_lrc(texto: str) -> list[tuple[float, str]]:
    """'[00:23.62] Ella durmió...' -> [(23.62, 'Ella durmió...'), ...]"""
    versos = []
    for linea in texto.split("\n"):
        coincidencia = _LINEA_LRC.match(linea.strip())
        if not coincidencia:
            continue
        minutos, segundos, fraccion, letra = coincidencia.groups()
        tiempo = int(minutos) * 60 + int(segundos)
        if fraccion:
            tiempo += float(f"0.{fraccion}")
        versos.append((tiempo, letra.strip()))
    versos.sort(key=lambda v: v[0])
    return versos


def _puntaje(candidato: dict, duracion) -> float:
    """Prefiere las que tienen letra sincronizada y duran lo mismo."""
    puntos = 0.0
    if candidato.get("syncedLyrics"):
        puntos += 10
    if duracion and candidato.get("duration"):
        diferencia = abs(float(candidato["duration"]) - float(duracion))
        if diferencia <= TOLERANCIA_DURACION:
            puntos += 5 - (diferencia / TOLERANCIA_DURACION)
        else:
            puntos -= diferencia / 60          # penaliza según lo lejos que esté
    if candidato.get("instrumental"):
        puntos -= 8
    return puntos


def buscar(titulo: str, artista=None, duracion=None) -> dict | None:
    """Devuelve {'versos', 'titulo', 'artista', 'duracion'} o None.

    'versos' es una lista de (segundo, texto) ordenada por tiempo.
    """
    consultas = []
    if artista:
        consultas.append({"artist_name": artista, "track_name": titulo})
    consultas.append({"q": f"{artista} {titulo}" if artista else titulo})

    for parametros in consultas:
        try:
            respuesta = requests.get(API, params=parametros, timeout=10,
                                     headers={"User-Agent": AGENTE})
            respuesta.raise_for_status()
            resultados = respuesta.json()
        except Exception:
            log.exception(f"[karaoke] Falló la búsqueda en lrclib: {parametros}")
            continue

        conectados = [r for r in resultados if r.get("syncedLyrics")]
        if not conectados:
            continue

        mejor = max(conectados, key=lambda r: _puntaje(r, duracion))
        versos = _parsear_lrc(mejor["syncedLyrics"])
        if not versos:
            continue

        log.info(f"[karaoke] {mejor.get('artistName')} - {mejor.get('trackName')} "
                 f"({len(versos)} versos)")
        return {
            "versos": versos,
            "titulo": mejor.get("trackName") or titulo,
            "artista": mejor.get("artistName") or (artista or ""),
            "duracion": mejor.get("duration"),
        }

    return None


def indice_actual(versos: list[tuple[float, str]], segundo: float) -> int:
    """Cuál verso está sonando. -1 si la canción todavía no llegó al primero."""
    indice = -1
    for i, (tiempo, _) in enumerate(versos):
        if tiempo <= segundo:
            indice = i
        else:
            break
    return indice


def ventana(versos: list[tuple[float, str]], actual: int,
            antes: int = 3, despues: int = 4) -> str:
    """Arma el bloque de texto: unos versos de contexto y el actual resaltado."""
    if not versos:
        return ""

    desde = max(0, actual - antes)
    hasta = min(len(versos), max(actual, 0) + despues + 1)

    lineas = []
    for i in range(desde, hasta):
        texto = versos[i][1] or "♪"
        if i == actual:
            lineas.append(f"**➤  {texto}**")
        else:
            lineas.append(f"　{texto}")
    return "\n".join(lineas)
