# -*- coding: utf-8 -*-
"""Letras con marcas de tiempo, para el modo karaoke.

Genius (que ya usa el bot para /lyrics) da la letra en texto plano, sin
tiempos. Para saber qué verso suena en cada segundo hace falta otra fuente:
lrclib.net, que es gratis, no pide API key y devuelve formato LRC:

    [00:23.62] Ella durmió al calor de las masas

Si una canción no tiene versión sincronizada, se avisa y el usuario se
queda con /lyrics, que sigue funcionando igual.
"""
import difflib
import logging
import re
import unicodedata

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


_FEAT = re.compile(r"\s*[\(\[]?\s*(?:feat\.?|ft\.?|featuring)\s[^)\]]*[\)\]]?", re.IGNORECASE)
_PARENTESIS = re.compile(r"[\(（]([^)）]+)[\)）]")


def _normalizar(texto: str) -> str:
    limpio = unicodedata.normalize("NFKD", (texto or "").lower())
    limpio = "".join(c for c in limpio if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^\w\s]", " ", limpio).split())


def _parecido(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, _normalizar(a), _normalizar(b)).ratio()


def variantes_artista(artista) -> list[str]:
    """Formas alternativas de escribir el nombre del artista.

    Hace falta porque lrclib es literal: '澤野弘之 (Hiroyuki Sawano)' devuelve
    cero resultados, mientras que 'Hiroyuki Sawano' devuelve la canción. De
    un nombre así sacamos el nombre sin el 'Ft.', la romanización que está
    entre paréntesis, y el nombre sin paréntesis."""
    if not artista:
        return []

    variantes: list[str] = []

    def agregar(valor: str):
        valor = (valor or "").strip(" -–—·,")
        if valor and valor not in variantes:
            variantes.append(valor)

    base = _FEAT.sub("", artista).strip()
    agregar(base)
    for dentro in _PARENTESIS.findall(base):
        agregar(dentro)
    agregar(_PARENTESIS.sub("", base))
    return variantes


def _aceptable(candidato: dict, artista, duracion) -> bool:
    """Filtra los resultados que claramente no son la canción.

    Buscar solo por título ('BITE DOWN') trae canciones distintas con el
    mismo nombre, así que exigimos que coincida la duración o el artista.
    Sin ninguna de las dos no hay forma de saber si es la correcta, y
    preferimos decir que no la encontramos antes que mostrar otra letra."""
    if duracion and candidato.get("duration"):
        if abs(float(candidato["duration"]) - float(duracion)) <= TOLERANCIA_DURACION:
            return True

    nombre = candidato.get("artistName") or ""
    return any(_parecido(v, nombre) >= 0.55 for v in variantes_artista(artista))


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
    variantes = variantes_artista(artista)

    consultas = []
    for variante in variantes:
        consultas.append({"artist_name": variante, "track_name": titulo})
    for variante in variantes:
        consultas.append({"q": f"{variante} {titulo}"})
    # Último recurso: solo el título. Trae canciones distintas que se llaman
    # igual, por eso después filtramos por duración o artista.
    consultas.append({"q": titulo})

    vistas = []
    for consulta in consultas:
        if consulta not in vistas:
            vistas.append(consulta)
    consultas = vistas

    for parametros in consultas:
        try:
            respuesta = requests.get(API, params=parametros, timeout=10,
                                     headers={"User-Agent": AGENTE})
            respuesta.raise_for_status()
            resultados = respuesta.json()
        except Exception:
            log.exception(f"[karaoke] Falló la búsqueda en lrclib: {parametros}")
            continue

        conectados = [r for r in resultados
                      if r.get("syncedLyrics") and _aceptable(r, artista, duracion)]
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
