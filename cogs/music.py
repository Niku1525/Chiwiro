import asyncio
import difflib
import html
import html.parser
import json
import logging
import math
import os
import random
import re
import subprocess
import sys
import threading
import time
import unicodedata
from collections import deque
from dataclasses import dataclass
from typing import Optional

import discord
from discord.ext import commands
from discord import Option
import requests
import yt_dlp

log = logging.getLogger("music")

YTDL_OPTS = {
    "format": "bestaudio/best",
    "noplaylist": True,
    "quiet": True,
    "no_warnings": True,
    "default_search": "ytsearch",
    "source_address": "0.0.0.0",
    "extract_flat": False,
    "remote_components": "ejs:github",
    "extractor_args": {
        "youtube": {
            "player_client": ["android", "ios", "mweb"]
        }
    },
}

_cookies_file = os.getenv("YTDLP_COOKIES_FILE")
_cookies_browser = os.getenv("YTDLP_COOKIES_BROWSER")
if _cookies_file:
    YTDL_OPTS["cookiefile"] = _cookies_file
    log.info(f"Usando cookies desde archivo: {_cookies_file}")
elif _cookies_browser:
    YTDL_OPTS["cookiesfrombrowser"] = (_cookies_browser,)
    log.info(f"Usando cookies de YouTube desde el navegador: {_cookies_browser}")

PCM_SAMPLE_RATE = 48000
PCM_CHANNELS = 2
PCM_BYTES_PER_SAMPLE = 2
PCM_BYTES_PER_SECOND = PCM_SAMPLE_RATE * PCM_CHANNELS * PCM_BYTES_PER_SAMPLE
FRAME_SIZE = 3840

PREBUFFER_SECONDS = float(os.getenv("PREBUFFER_SECONDS", "30"))
PREBUFFER_BYTES = int(PREBUFFER_SECONDS * PCM_BYTES_PER_SECOND)

MAX_BUFFER_BYTES = int(os.getenv("MAX_BUFFER_BYTES", str(500 * 1024 * 1024)))

AUTO_DISCONNECT_SECONDS = float(os.getenv("AUTO_DISCONNECT_SECONDS", "120"))

MAX_HISTORY = 100

ytdl = yt_dlp.YoutubeDL(YTDL_OPTS)

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SETTINGS_PATH = os.path.join(_PROJECT_ROOT, "guild_settings.json")
_settings_lock = threading.Lock()

# Favoritos persistentes por usuario.
# Se guarda únicamente una URL por línea en:
# F:\\Music_Bot\\favorites\\<user_id>.txt
FAVORITES_DIR = os.path.join(_PROJECT_ROOT, "favorites")
os.makedirs(FAVORITES_DIR, exist_ok=True)
_favorites_lock = threading.Lock()


def _load_settings() -> dict:
    if not os.path.exists(SETTINGS_PATH):
        return {}
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        log.exception("No se pudo leer guild_settings.json, empiezo de cero")
        return {}


def _save_settings(data: dict):
    try:
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        log.exception("No se pudo guardar guild_settings.json")


_settings = _load_settings()


def get_guild_volume(guild_id: int) -> float:
    with _settings_lock:
        return _settings.get(str(guild_id), {}).get("volume", 0.5)


def set_guild_volume(guild_id: int, volume: float):
    with _settings_lock:
        _settings.setdefault(str(guild_id), {})["volume"] = volume
        _save_settings(_settings)


def _favorites_path(user_id: int) -> str:
    return os.path.join(FAVORITES_DIR, f"{user_id}.txt")


def get_favorites(user_id: int) -> list[str]:
    path = _favorites_path(user_id)

    if not os.path.exists(path):
        return []

    try:
        with _favorites_lock:
            with open(path, "r", encoding="utf-8") as f:
                return [line.strip() for line in f if line.strip()]
    except Exception:
        log.exception(f"No se pudieron leer los favoritos de {user_id}")
        return []


def save_favorites(user_id: int, favorites: list[str]) -> None:
    path = _favorites_path(user_id)

    try:
        with _favorites_lock:
            with open(path, "w", encoding="utf-8") as f:
                for url in favorites:
                    f.write(url + "\n")
    except Exception:
        log.exception(f"No se pudieron guardar los favoritos de {user_id}")


def add_favorite(user_id: int, url: str) -> bool:
    favorites = get_favorites(user_id)

    if url in favorites:
        return False

    favorites.append(url)
    save_favorites(user_id, favorites)
    return True


def remove_favorite(user_id: int, index: int) -> Optional[str]:
    favorites = get_favorites(user_id)

    if index < 0 or index >= len(favorites):
        return None

    removed = favorites.pop(index)
    save_favorites(user_id, favorites)
    return removed


def _cookie_cli_args() -> list[str]:
    if _cookies_file:
        return ["--cookies", _cookies_file]
    elif _cookies_browser:
        return ["--cookies-from-browser", _cookies_browser]
    return []


def spawn_playback_pipeline(webpage_url: str) -> tuple[subprocess.Popen, subprocess.Popen]:
    ytdlp_args = [
        sys.executable, "-m", "yt_dlp",
        "-f", "bestaudio/best",
        "-o", "-",
        "--quiet",
        "--no-warnings",
        "--no-playlist",
        "--remote-components", "ejs:github",
        "--extractor-args", "youtube:player_client=android,ios,mweb",
        *_cookie_cli_args(),
        webpage_url,
    ]
    ytdlp_proc = subprocess.Popen(
        ytdlp_args,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        bufsize=0,
    )

    ffmpeg_args = [
        "ffmpeg",
        "-i", "-",
        "-f", "s16le",
        "-ar", str(PCM_SAMPLE_RATE),
        "-ac", str(PCM_CHANNELS),
        "-loglevel", "warning",
        "-vn",
        "pipe:1",
    ]
    ffmpeg_proc = subprocess.Popen(
        ffmpeg_args,
        stdin=ytdlp_proc.stdout,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        bufsize=0,
    )
    ytdlp_proc.stdout.close()

    return ytdlp_proc, ffmpeg_proc


class BufferedPCMSource(discord.AudioSource):
    def __init__(self, stdout_stream, prebuffer_bytes: int = PREBUFFER_BYTES, max_buffer_bytes: int = MAX_BUFFER_BYTES):
        self._stream = stdout_stream
        self._buffer = bytearray()
        self._read_pos = 0
        self._cond = threading.Condition()
        self._eof = False
        self._closed = False
        self._prebuffer_bytes = min(prebuffer_bytes, max_buffer_bytes)
        self._max_buffer_bytes = max_buffer_bytes
        self._ready_event = threading.Event()
        self._underrun_started_at: Optional[float] = None
        self._reader_thread = threading.Thread(target=self._reader, daemon=True)
        self._reader_thread.start()

    def _pending_bytes(self) -> int:
        return len(self._buffer) - self._read_pos

    def _reader(self):
        try:
            while True:
                if self._closed:
                    return
                chunk = self._stream.read(65536)
                if not chunk:
                    with self._cond:
                        self._eof = True
                        self._ready_event.set()
                        self._cond.notify_all()
                    return
                with self._cond:
                    while self._pending_bytes() >= self._max_buffer_bytes and not self._closed:
                        self._cond.wait(timeout=1.0)
                    if self._closed:
                        return
                    self._buffer.extend(chunk)
                    if not self._ready_event.is_set() and self._pending_bytes() >= self._prebuffer_bytes:
                        self._ready_event.set()
                    self._cond.notify_all()
        except Exception:
            log.exception("Error leyendo el stream de audio")
            with self._cond:
                self._eof = True
                self._ready_event.set()
                self._cond.notify_all()

    def wait_until_ready(self, timeout: float = 20.0):
        self._ready_event.wait(timeout)

    def read(self) -> bytes:
        with self._cond:
            if self._pending_bytes() >= FRAME_SIZE:
                if self._underrun_started_at is not None:
                    stalled_seconds = time.monotonic() - self._underrun_started_at
                    log.warning(
                        f"[buffer] Se recuperó después de {stalled_seconds:.2f}s sin datos "
                        f"suficientes (buffer pendiente al recuperar: {self._pending_bytes()} bytes)."
                    )
                    self._underrun_started_at = None
                start = self._read_pos
                end = start + FRAME_SIZE
                data = bytes(self._buffer[start:end])
                self._read_pos = end
                if self._read_pos >= 1_048_576 or self._read_pos * 2 >= len(self._buffer):
                    del self._buffer[:self._read_pos]
                    self._read_pos = 0
                self._cond.notify_all()
                return data
            if self._eof:
                if self._pending_bytes() <= 0:
                    return b""
                data = bytes(self._buffer[self._read_pos:]).ljust(FRAME_SIZE, b"\x00")
                self._buffer.clear()
                self._read_pos = 0
                self._cond.notify_all()
                return data
            if self._underrun_started_at is None:
                self._underrun_started_at = time.monotonic()
                log.warning(
                    f"[buffer] Se quedó sin datos suficientes (solo {self._pending_bytes()} de "
                    f"{FRAME_SIZE} bytes necesarios) — va a sonar cortado hasta que se recupere."
                )
        return b"\x00" * FRAME_SIZE

    def is_opus(self) -> bool:
        return False

    def cleanup(self) -> None:
        with self._cond:
            self._closed = True
            self._cond.notify_all()


def format_duration(seconds: Optional[float]) -> str:
    if not seconds:
        return "en vivo"
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def build_progress_bar(elapsed: float, total: Optional[float], length: int = 20) -> str:
    if not total:
        return "🔴 En vivo / duración desconocida"
    ratio = max(0.0, min(elapsed / total, 1.0))
    filled = int(ratio * length)
    filled = min(filled, length - 1)
    bar = "▬" * filled + "🔘" + "▬" * (length - filled - 1)
    return f"{bar}\n`{format_duration(elapsed)} / {format_duration(total)}`"


def pick_thumbnail(info: dict) -> Optional[str]:
    thumb = info.get("thumbnail")
    if thumb:
        return thumb
    thumbs = info.get("thumbnails")
    if thumbs:
        return thumbs[-1].get("url")
    return None


SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")

SPOTIFY_URL_RE = re.compile(
    r"open\.spotify\.com/(?:intl-[a-z]{2}/)?(track|album|playlist)/([A-Za-z0-9]+)"
)

_spotify_token: Optional[str] = None
_spotify_token_expiry: float = 0.0
_spotify_lock = threading.Lock()


def spotify_configured() -> bool:
    return bool(SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET)


def parse_spotify_url(url: str) -> Optional[tuple[str, str]]:
    match = SPOTIFY_URL_RE.search(url)
    if not match:
        return None
    return match.group(1), match.group(2)


def _get_spotify_token() -> str:
    global _spotify_token, _spotify_token_expiry
    with _spotify_lock:
        if _spotify_token and time.time() < _spotify_token_expiry - 30:
            return _spotify_token
        resp = requests.post(
            "https://accounts.spotify.com/api/token",
            data={"grant_type": "client_credentials"},
            auth=(SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET),
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        _spotify_token = data["access_token"]
        _spotify_token_expiry = time.time() + data.get("expires_in", 3600)
        return _spotify_token


def _spotify_get(path: str, params: Optional[dict] = None) -> dict:
    token = _get_spotify_token()
    resp = requests.get(
        f"https://api.spotify.com/v1{path}",
        headers={"Authorization": f"Bearer {token}"},
        params=params,
        timeout=10,
    )
    if not resp.ok:
        log.error(f"Spotify API {resp.status_code} en {path}: {resp.text}")
    resp.raise_for_status()
    return resp.json()


_SPOTIFY_META_RE_CACHE: dict[str, re.Pattern] = {}


def _spotify_meta_tag(html_text: str, prop: str) -> Optional[str]:
    if prop not in _SPOTIFY_META_RE_CACHE:
        _SPOTIFY_META_RE_CACHE[prop] = re.compile(
            r'<meta[^>]+(?:property|name)=["\']' + re.escape(prop) + r'["\'][^>]+content=["\']([^"\']*)["\']'
            r'|<meta[^>]+content=["\']([^"\']*)["\'][^>]+(?:property|name)=["\']' + re.escape(prop) + r'["\']'
        )
    match = _SPOTIFY_META_RE_CACHE[prop].search(html_text)
    if not match:
        return None
    return html.unescape(match.group(1) or match.group(2))


def fetch_spotify_track_public(item_id: str) -> dict:
    resp = requests.get(
        f"https://open.spotify.com/track/{item_id}",
        headers={"User-Agent": "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"},
        timeout=10,
    )
    resp.raise_for_status()
    page = resp.text
    title = _spotify_meta_tag(page, "og:title") or ""
    artist = _spotify_meta_tag(page, "music:musician_description") or ""
    if not title:
        log.error(
            f"No encontré meta tags en la página de Spotify para {item_id}. "
            f"Longitud de la respuesta: {len(page)} bytes. "
            f"Primeros 500 caracteres: {page[:500]!r}"
        )
    return {"title": title, "artists": artist}


def fetch_spotify_tracks(kind: str, item_id: str) -> list[dict]:
    tracks: list[dict] = []

    if kind == "track":
        return [fetch_spotify_track_public(item_id)]

    if kind == "album":
        album = _spotify_get(f"/albums/{item_id}")
        album_artists = ", ".join(a["name"] for a in album.get("artists", []))
        items = album.get("tracks", {}).get("items", [])
        total = album.get("tracks", {}).get("total", len(items))
        offset = len(items)
        all_items = list(items)
        while offset < total:
            page = _spotify_get(
                f"/albums/{item_id}/tracks", params={"limit": 50, "offset": offset}
            )
            page_items = page.get("items", [])
            if not page_items:
                break
            all_items.extend(page_items)
            offset += len(page_items)
        for t in all_items:
            artists = ", ".join(a["name"] for a in t.get("artists", [])) or album_artists
            tracks.append({"title": t.get("name", ""), "artists": artists})
        return tracks

    if kind == "playlist":
        offset = 0
        while True:
            page = _spotify_get(
                f"/playlists/{item_id}/tracks",
                params={
                    "limit": 100,
                    "offset": offset,
                    "fields": "items(track(name,artists(name))),next",
                },
            )
            items = page.get("items", [])
            if not items:
                break
            for it in items:
                t = it.get("track")
                if not t:
                    continue
                artists = ", ".join(a["name"] for a in t.get("artists", []))
                tracks.append({"title": t.get("name", ""), "artists": artists})
            offset += len(items)
            if not page.get("next"):
                break
        return tracks

    return tracks


GENIUS_ACCESS_TOKEN = os.getenv("GENIUS_ACCESS_TOKEN")

# Umbrales de confianza al elegir un resultado de Genius:
#   score >= LYRICS_AUTO_SCORE     -> lo damos por bueno y mostramos la letra.
#   entre SUGGEST y AUTO           -> NO adivinamos: le mostramos las opciones
#                                     al usuario para que elija.
#   score <  LYRICS_SUGGEST_SCORE  -> lo descartamos, ni lo ofrecemos.
LYRICS_AUTO_SCORE = 0.70
LYRICS_SUGGEST_SCORE = 0.30
LYRICS_MAX_CANDIDATES = 8

# Cachés de sesión (se vacían al reiniciar el bot).
_lyrics_text_cache: dict[str, str] = {}      # url de Genius -> letra
_lyrics_choice_cache: dict[str, dict] = {}   # url de YouTube -> candidato elegido a mano
_LYRICS_CACHE_MAX = 200


def genius_configured() -> bool:
    return bool(GENIUS_ACCESS_TOKEN)


def _cache_put(cache: dict, key: str, value) -> None:
    if len(cache) >= _LYRICS_CACHE_MAX:
        cache.pop(next(iter(cache)), None)
    cache[key] = value


# --------------------------------------------------------------------------
# Normalización de títulos
# --------------------------------------------------------------------------

# Palabras que aparecen en los títulos de YouTube pero no son parte del
# nombre real de la canción. Se usan para dos cosas: limpiar el título antes
# de buscar, y que no inflen el parecido al comparar candidatos.
_NOISE_WORDS = {
    "official", "oficial", "officiel", "video", "videoclip", "clip",
    "audio", "lyric", "lyrics", "letra", "letras", "mv", "hd", "hq", "4k",
    "8k", "1080p", "720p", "full", "visualizer", "visualiser", "remastered",
    "remaster", "explicit", "sub", "subtitulado", "subtitulada", "subtitulos",
    "espanol", "english", "eng", "kan", "rom", "romaji", "color", "coded",
    "traducida", "traduccion", "traducao", "music", "musica", "song",
    "topic", "theme", "hi", "res", "new", "with",
}

# Cuentas de Genius que suben traducciones en vez de la letra original.
_TRANSLATION_MARKERS = ("traduccion", "traducciones", "translation", "translations", "traducao")

_BRACKET_RE = re.compile(r"[\(\[\{【「（][^\)\]\}】」）]*[\)\]\}】」）]")
# El "ft. Fulano" se corta hasta el próximo separador, no hasta el final:
# si no, en "Duki ft. YSY A - Hijo de la Noche" se comería el título entero.
_FEAT_RE = re.compile(r"\s*(?:feat\.?|ft\.?|featuring)\s+[^\-–—|(\[]+", re.IGNORECASE)
_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)
_UPLOADER_NOISE_RE = re.compile(
    r"\s*-\s*topic$|\s*vevo$|\s*official$|\s*oficial$|\s*music$|\s*channel$|\s*records$",
    re.IGNORECASE,
)


def _strip_accents(text: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)
    )


def _normalize(text: str) -> str:
    """minúsculas, sin acentos y sin puntuación: 'Amor Mío (Live)' -> 'amor mio live'."""
    text = _strip_accents(text.lower()).replace("&", " and ")
    return " ".join(_PUNCT_RE.sub(" ", text).split())


def _token_set(text: str) -> set[str]:
    return {t for t in _normalize(text).split() if t not in _NOISE_WORDS}


def _similarity(a: str, b: str) -> float:
    """Parecido entre dos títulos, de 0 a 1.

    Mezcla el parecido carácter a carácter con el parecido por *palabras*.
    Lo segundo es justamente lo que evita confundir "Amor mío" con "El amor
    que ya no es mío": comparten un montón de letras (y por eso el método
    viejo, que solo miraba caracteres, las daba casi por iguales), pero como
    conjuntos de palabras uno es mucho más grande que el otro."""
    na, nb = _normalize(a), _normalize(b)
    if not na or not nb:
        return 0.0
    seq = difflib.SequenceMatcher(None, na, nb).ratio()
    ta, tb = _token_set(a), _token_set(b)
    if not ta or not tb:
        return seq
    # Dividir por el conjunto más grande castiga a los candidatos que traen
    # palabras de más ("el", "que", "ya", "no", "es"...).
    token = len(ta & tb) / max(len(ta), len(tb))
    return 0.6 * token + 0.4 * seq


def _drop_noise_brackets(title: str) -> str:
    """Saca los paréntesis/corchetes que son puro ruido ("(Official Video)",
    "【MV】", "[Lyrics]") pero deja los que sí cambian de qué canción estamos
    hablando ("(Remix)", "(Live at Wembley)", "(Acoustic)")."""

    def _replace(match: "re.Match") -> str:
        words = set(_normalize(match.group(0)[1:-1]).split())
        # Los años sueltos también son ruido: "(Remastered 2007)", "(HD 2019)".
        is_noise = bool(words) and all(w in _NOISE_WORDS or w.isdigit() for w in words)
        return " " if is_noise else match.group(0)

    return _BRACKET_RE.sub(_replace, title)


def _drop_noise_tail(title: str) -> str:
    """Corta las colas tipo 'Canción | Official Video' o 'Canción • 4K'."""
    parts = re.split(r"\s*[|•·]\s*", title)
    while len(parts) > 1:
        words = set(_normalize(parts[-1]).split())
        if words and words <= _NOISE_WORDS:
            parts.pop()
        else:
            break
    return " | ".join(parts)


def clean_title_for_lyrics_search(title: str) -> str:
    cleaned = _drop_noise_tail(_drop_noise_brackets(title))
    cleaned = _FEAT_RE.sub(" ", cleaned)
    cleaned = " ".join(cleaned.split()).strip(" -–—|/•·")
    return cleaned or title


def split_artist_title(title: str) -> tuple[Optional[str], str]:
    """'Artista - Canción' -> ('Artista', 'Canción'). Si no hay guion
    separador devuelve (None, título tal cual)."""
    parts = re.split(r"\s+[-–—]\s+", title, maxsplit=1)
    if len(parts) == 2 and parts[0].strip() and parts[1].strip():
        return parts[0].strip(), parts[1].strip()
    return None, title.strip()


def clean_artist_name(name: Optional[str]) -> Optional[str]:
    """Limpia el nombre del canal de YouTube: 'Shakira - Topic' -> 'Shakira',
    'ShakiraVEVO' -> 'Shakira'. Devuelve None si el canal no parece ser el
    nombre de un artista (ej. 'Rock Nacional Mix 2024 Hits')."""
    if not name:
        return None
    cleaned = name.strip()
    is_topic = cleaned.lower().endswith("- topic")
    for _ in range(3):
        new = _UPLOADER_NOISE_RE.sub("", cleaned).strip(" -–—")
        if new == cleaned:
            break
        cleaned = new
    cleaned = re.sub(r"vevo$", "", cleaned, flags=re.IGNORECASE).strip()
    if not cleaned:
        return None
    # Los canales "- Topic" los genera YouTube Music: ahí el nombre del canal
    # ES el artista, así que le creemos aunque sea largo.
    return cleaned if (is_topic or len(cleaned.split()) <= 4) else None


def build_lyrics_queries(
    raw_title: str, artist_hint: Optional[str] = None
) -> tuple[str, Optional[str], list[str]]:
    """Arma varias consultas para Genius, de la más específica a la más
    genérica. Antes se probaba una sola: si esa fallaba, el bot decía que no
    encontró la letra aunque la canción estuviera ahí."""
    cleaned = clean_title_for_lyrics_search(raw_title)
    split_artist, split_title = split_artist_title(cleaned)
    channel_artist = clean_artist_name(artist_hint)
    artist = split_artist or channel_artist

    queries: list[str] = []
    for candidate_query in (
        f"{artist} {split_title}" if artist else None,
        f"{channel_artist} {split_title}" if channel_artist and channel_artist != artist else None,
        split_title,
        cleaned,
        " ".join(_BRACKET_RE.sub(" ", split_title).split()),  # sin ningún paréntesis
    ):
        candidate_query = (candidate_query or "").strip()
        if candidate_query and candidate_query not in queries:
            queries.append(candidate_query)

    return split_title, artist, queries


# --------------------------------------------------------------------------
# Búsqueda en Genius
# --------------------------------------------------------------------------

def _genius_search(query: str, per_page: int = 10) -> list[dict]:
    resp = requests.get(
        "https://api.genius.com/search",
        params={"q": query, "per_page": per_page},
        headers={"Authorization": f"Bearer {GENIUS_ACCESS_TOKEN}"},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json().get("response", {}).get("hits", [])


def _score_candidate(result: dict, want_title: str, want_artist: Optional[str]) -> float:
    cand_title = result.get("title") or ""
    cand_artist = result.get("artist_names") or (result.get("primary_artist") or {}).get("name") or ""
    cand_full = result.get("full_title") or f"{cand_title} {cand_artist}"

    score = max(
        _similarity(want_title, cand_title),
        # El título de YouTube suele venir como "Artista - Canción" y el
        # full_title de Genius como "Canción by Artista": comparar los
        # enteros también sirve, pero vale un poco menos que el match limpio.
        0.9 * _similarity(f"{want_artist} {want_title}" if want_artist else want_title, cand_full),
    )

    if want_artist:
        # Mezclamos título y artista en vez de sumar un bonus con tope: así
        # entre dos canciones que se llaman igual siempre gana la del
        # artista correcto, en vez de empatar las dos en 1.00.
        score = 0.8 * score + 0.2 * _similarity(want_artist, cand_artist)

    if result.get("lyrics_state") != "complete":
        score *= 0.6
    if any(marker in _normalize(cand_artist) for marker in _TRANSLATION_MARKERS):
        score *= 0.5                            # es una traducción, no la letra original
    if result.get("instrumental"):
        score *= 0.5

    return round(score, 4)


def search_genius_candidates(raw_title: str, artist_hint: Optional[str] = None) -> list[dict]:
    """Devuelve los candidatos de Genius ordenados por confianza (mejor
    primero), ya filtrados por el umbral mínimo."""
    want_title, want_artist, queries = build_lyrics_queries(raw_title, artist_hint)
    log.info(f"[letras] Buscando {raw_title!r} -> título={want_title!r} artista={want_artist!r}")

    by_id: dict[int, dict] = {}
    for query in queries[:4]:
        try:
            hits = _genius_search(query)
        except Exception:
            log.exception(f"[letras] Falló la búsqueda en Genius para {query!r}")
            continue

        for hit in hits:
            result = hit.get("result") or {}
            song_id = result.get("id")
            if not song_id or not result.get("url") or song_id in by_id:
                continue
            by_id[song_id] = {
                "id": song_id,
                "title": result.get("title") or "",
                "artist": result.get("artist_names")
                or (result.get("primary_artist") or {}).get("name")
                or "",
                "full_title": result.get("full_title") or "",
                "url": result.get("url"),
                "score": _score_candidate(result, want_title, want_artist),
            }

        # Si ya tenemos una coincidencia clara, no gastamos más llamadas.
        if by_id and max(c["score"] for c in by_id.values()) >= LYRICS_AUTO_SCORE:
            break

    candidates = sorted(by_id.values(), key=lambda c: c["score"], reverse=True)
    candidates = [c for c in candidates if c["score"] >= LYRICS_SUGGEST_SCORE]
    if candidates:
        log.info(
            f"[letras] Mejor candidato: {candidates[0]['full_title']!r} "
            f"(confianza {candidates[0]['score']:.2f})"
        )
    return candidates[:LYRICS_MAX_CANDIDATES]


class _GeniusLyricsParser(html.parser.HTMLParser):
    """Parser liviano (sin dependencias externas) que junta el texto que
    está dentro de los <div data-lyrics-container="true"> de una página de
    Genius. Convierte <br> en saltos de línea y descarta todo lo demás
    (anotaciones, links a colaboradores, etc.)."""

    def __init__(self):
        super().__init__()
        self._depth_stack: list[int] = []
        self._current_depth = 0
        self.chunks: list[str] = []

    def handle_starttag(self, tag, attrs):
        self._current_depth += 1
        if tag == "div" and any(k == "data-lyrics-container" and v == "true" for k, v in attrs):
            self._depth_stack.append(self._current_depth)
        elif tag == "br" and self._depth_stack:
            self.chunks.append("\n")

    def handle_startendtag(self, tag, attrs):
        if tag == "br" and self._depth_stack:
            self.chunks.append("\n")

    def handle_endtag(self, tag):
        if self._depth_stack and self._current_depth == self._depth_stack[-1] and tag == "div":
            self._depth_stack.pop()
        self._current_depth = max(0, self._current_depth - 1)

    def handle_data(self, data):
        if self._depth_stack:
            self.chunks.append(data)

    def get_lyrics(self) -> str:
        text = "".join(self.chunks)
        lines = [line.strip() for line in text.split("\n")]
        # Colapsa 3+ líneas vacías seguidas en una sola, sin perder los
        # saltos entre estrofas.
        result_lines: list[str] = []
        blank_streak = 0
        for line in lines:
            if line == "":
                blank_streak += 1
                if blank_streak > 1:
                    continue
            else:
                blank_streak = 0
            result_lines.append(line)

        # Genius mete en la misma caja un encabezado que no es la letra:
        # "25 ContributorsTranslationsEnglish…Título Lyrics…Read More".
        # Lo cortamos para que el embed arranque directo en la canción.
        if result_lines:
            head = result_lines[0]
            if "Contributor" in head or "Translations" in head:
                for marker in ("… Read More", "... Read More", "Read More"):
                    if marker in head:
                        head = head.split(marker)[-1]
                        break
                else:
                    idx = head.rfind("Lyrics")
                    if idx != -1:
                        head = head[idx + len("Lyrics"):]
                result_lines[0] = head.strip()

        return "\n".join(result_lines).strip()


def scrape_genius_lyrics(song_url: str) -> Optional[str]:
    cached = _lyrics_text_cache.get(song_url)
    if cached is not None:
        return cached

    resp = requests.get(
        song_url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        },
        timeout=10,
    )
    resp.raise_for_status()
    parser = _GeniusLyricsParser()
    parser.feed(resp.text)
    lyrics = parser.get_lyrics()
    if lyrics:
        _cache_put(_lyrics_text_cache, song_url, lyrics)
    return lyrics or None


def remember_lyrics_choice(song_key: Optional[str], candidate: dict) -> None:
    """Si el usuario corrigió a mano qué canción era, nos lo acordamos para
    esta sesión: la próxima vez que suene ese mismo video no volvemos a
    adivinar."""
    if song_key:
        _cache_put(_lyrics_choice_cache, song_key, candidate)


def resolve_lyrics(
    raw_title: str, artist_hint: Optional[str] = None, song_key: Optional[str] = None
) -> dict:
    """Busca la letra y devuelve un dict con:

      status     -> "ok" (encontrada y confiable) | "ambiguous" (hay
                    candidatos pero ninguno seguro) | "not_found"
      lyrics     -> texto de la letra (solo si status == "ok")
      song       -> candidato elegido (title/artist/url/score)
      candidates -> lista de candidatos para que elija el usuario
    """
    if song_key:
        chosen = _lyrics_choice_cache.get(song_key)
        if chosen:
            try:
                lyrics = scrape_genius_lyrics(chosen["url"])
            except Exception:
                log.exception(f"[letras] Falló la letra recordada de {song_key!r}")
                lyrics = None
            if lyrics:
                return {"status": "ok", "lyrics": lyrics, "song": chosen, "candidates": []}

    candidates = search_genius_candidates(raw_title, artist_hint)
    if not candidates:
        return {"status": "not_found", "lyrics": None, "song": None, "candidates": []}

    best = candidates[0]

    # Dos canciones distintas que puntúan casi igual (típico: mismo título,
    # artistas diferentes) es un empate, no una certeza: preguntamos.
    runner_up = candidates[1] if len(candidates) > 1 else None
    empate = (
        runner_up is not None
        and best["score"] - runner_up["score"] <= 0.04
        and _normalize(best["artist"]) != _normalize(runner_up["artist"])
    )

    if best["score"] < LYRICS_AUTO_SCORE or empate:
        # Acá está la diferencia grande con la versión anterior: si no
        # estamos seguros, NO mandamos la letra de cualquier canción
        # parecida — devolvemos las opciones para que las vea el usuario.
        return {"status": "ambiguous", "lyrics": None, "song": None, "candidates": candidates}

    try:
        lyrics = scrape_genius_lyrics(best["url"])
    except Exception:
        log.exception(f"[letras] No se pudo bajar la letra de {best['url']!r}")
        lyrics = None

    if not lyrics:
        return {
            "status": "ambiguous",
            "lyrics": None,
            "song": None,
            "candidates": candidates[1:] or candidates,
        }

    return {"status": "ok", "lyrics": lyrics, "song": best, "candidates": candidates}


def build_lyrics_embeds(song: dict, lyrics: str) -> list[discord.Embed]:
    """Parte la letra en embeds de 4000 caracteres, cortando en saltos de
    línea para no partir un verso al medio."""
    display_title = " - ".join(p for p in (song.get("artist"), song.get("title")) if p) or "Letra"

    chunks: list[str] = []
    current = ""
    for line in lyrics.split("\n"):
        line = line[:4000]
        if len(current) + len(line) + 1 > 4000:
            chunks.append(current.strip("\n"))
            current = ""
        current += line + "\n"
    if current.strip():
        chunks.append(current.strip("\n"))
    if not chunks:
        chunks = [lyrics[:4000]]

    embeds = []
    for i, chunk in enumerate(chunks, start=1):
        embed = discord.Embed(
            title=f"📜 Letra: {display_title}"[:256] if i == 1 else None,
            description=chunk,
            color=discord.Color.blurple(),
            url=song.get("url") if i == 1 else None,
        )
        footer = "Fuente: Genius" if len(chunks) == 1 else f"Parte {i}/{len(chunks)} · Fuente: Genius"
        score = song.get("score")
        if i == len(chunks) and isinstance(score, (int, float)) and score < 0.9:
            footer += f" · coincidencia {score:.0%}"
        embed.set_footer(text=footer)
        embeds.append(embed)
    return embeds


async def _disable_view(view: discord.ui.View) -> None:
    """Apaga los botones de una vista al vencer el tiempo, para que no queden
    clickeables dando 'la interacción falló'."""
    for item in view.children:
        item.disabled = True
    message = getattr(view, "message", None)
    if message is not None:
        try:
            await message.edit(view=view)
        except discord.HTTPException:
            pass


class LyricsPickerView(discord.ui.View):
    """Menú para elegir a mano cuál era la canción cuando el bot no está
    seguro (o cuando eligió mal)."""

    def __init__(self, candidates: list[dict], song_key: Optional[str] = None):
        super().__init__(timeout=300)
        self.candidates = candidates[:25]
        self.song_key = song_key

        options = []
        for i, cand in enumerate(self.candidates):
            label = (cand.get("full_title") or f"{cand['artist']} - {cand['title']}").strip()
            options.append(
                discord.SelectOption(
                    label=label[:100] or "Sin título",
                    description=f"Coincidencia aproximada: {cand['score']:.0%}"[:100],
                    value=str(i),
                )
            )

        self.select = discord.ui.Select(placeholder="Elegí la canción correcta...", options=options)
        self.select.callback = self.on_select
        self.add_item(self.select)

    async def on_select(self, interaction: discord.Interaction):
        await interaction.response.defer()
        candidate = self.candidates[int(self.select.values[0])]

        loop = asyncio.get_event_loop()
        try:
            lyrics = await loop.run_in_executor(None, scrape_genius_lyrics, candidate["url"])
        except Exception:
            log.exception(f"[letras] Falló la descarga de {candidate['url']!r}")
            lyrics = None

        if not lyrics:
            await interaction.followup.send(
                f"No pude leer la letra de **{candidate.get('full_title')}**. "
                f"Podés verla acá: {candidate['url']}",
                ephemeral=True,
            )
            return

        remember_lyrics_choice(self.song_key, candidate)

        for embed in build_lyrics_embeds(candidate, lyrics):
            await interaction.followup.send(embed=embed)

        for item in self.children:
            item.disabled = True
        try:
            await interaction.edit_original_response(
                content=f"✅ Listo, la letra de **{candidate.get('full_title')}**.", view=self
            )
        except discord.HTTPException:
            pass
        self.stop()

    async def on_timeout(self):
        await _disable_view(self)


class LyricsCorrectionView(discord.ui.View):
    """Botón que se cuelga de la letra publicada por si el bot se equivocó
    de canción: abre el menú con el resto de los candidatos."""

    def __init__(self, candidates: list[dict], song_key: Optional[str] = None):
        super().__init__(timeout=600)
        self.candidates = candidates
        self.song_key = song_key

    @discord.ui.button(label="🔎 No es esta canción", style=discord.ButtonStyle.secondary)
    async def pick_other(self, button: discord.ui.Button, interaction: discord.Interaction):
        if not self.candidates:
            await interaction.response.send_message(
                "No tengo otras opciones para esta canción. Probá con `/lyrics <nombre exacto>`.",
                ephemeral=True,
            )
            return
        await interaction.response.send_message(
            "Elegí cuál era la canción:",
            view=LyricsPickerView(self.candidates, self.song_key),
            ephemeral=True,
        )

    async def on_timeout(self):
        await _disable_view(self)


@dataclass
class Song:
    title: str
    webpage_url: str
    duration: Optional[int]
    requester: str
    thumbnail: Optional[str] = None
    # Canal de YouTube (o artista, si yt-dlp lo trae). Se usa como pista
    # para buscar la letra correcta.
    uploader: Optional[str] = None


def build_now_playing_embed(song: Song, elapsed: float, loop_mode: str) -> discord.Embed:
    embed = discord.Embed(
        title="🎵 Reproduciendo ahora",
        description=f"**[{song.title}]({song.webpage_url})**\n\n{build_progress_bar(elapsed, song.duration)}",
        color=discord.Color.blurple(),
    )
    if song.thumbnail:
        embed.set_thumbnail(url=song.thumbnail)
    footer = f"Pedido por {song.requester}"
    if loop_mode == "song":
        footer += " • 🔂 Repitiendo esta canción"
    elif loop_mode == "queue":
        footer += " • 🔁 Repitiendo la cola"
    embed.set_footer(text=footer)
    return embed


def format_queue_text(state: "GuildMusicState") -> str:
    if not state.current and not state.queue and getattr(state, "active_playlist", None) is None:
        return "La cola está vacía."
    lines = []
    if state.current:
        lines.append(f"**Sonando ahora:** {state.current.title}")
    if state.queue:
        lines.append("\n**En cola:**")
        for i, song in enumerate(state.queue, start=1):
            lines.append(f"{i}. {song.title} — pedido por {song.requester}")
            
    # NUEVO: Mostrar el progreso de la lista en segundo plano
    pl = getattr(state, "active_playlist", None)
    if pl:
        restantes = len(pl["entries"]) - pl["current_index"]
        if restantes > 0:
            lines.append(f"\n🎶 **Playlist en segundo plano:** {pl['title']} ({restantes} canciones restantes)")
            
    if state.loop_mode != "off":
        mode_label = "🔂 canción actual" if state.loop_mode == "song" else "🔁 toda la cola"
        lines.append(f"\nRepetición activa: {mode_label}")
    return "\n".join(lines)


class FavoritesMenuView(discord.ui.View):
    def __init__(self, cog: "Music", guild_id: int):
        super().__init__(timeout=90)
        self.cog = cog
        self.guild_id = guild_id

    @discord.ui.button(
        label="⭐ Añadir a Favoritos",
        style=discord.ButtonStyle.success,
        row=0,
    )
    async def add_favorite(
        self,
        button: discord.ui.Button,
        interaction: discord.Interaction,
    ):
        state = self.cog.get_state(self.guild_id)

        if state.current is None:
            await interaction.response.send_message(
                "❌ No hay ninguna canción reproduciéndose.",
                ephemeral=True,
            )
            return

        if add_favorite(interaction.user.id, state.current.webpage_url):
            await interaction.response.send_message(
                f"⭐ **{state.current.title}** fue añadida a tus favoritos.",
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                "⭐ Esa canción ya está en tus favoritos.",
                ephemeral=True,
            )

    @discord.ui.button(
        label="📋 Seleccionar Favoritos",
        style=discord.ButtonStyle.primary,
        row=1,
    )
    async def select_favorite(
        self,
        button: discord.ui.Button,
        interaction: discord.Interaction,
    ):
        favorites = get_favorites(interaction.user.id)

        if not favorites:
            await interaction.response.send_message(
                "📋 No tienes ninguna canción en favoritos.",
                ephemeral=True,
            )
            return

        # Resolver los títulos de los favoritos puede tardar más de 3 segundos.
        # Primero reconocemos la interacción para evitar "Unknown interaction".
        await interaction.response.defer(ephemeral=True)

        view = FavoriteSelectView(
            self.cog,
            self.guild_id,
            interaction.user.id,
            action="play",
        )
        await view.load_page()

        await interaction.edit_original_response(
            content=view.page_message(),
            view=view,
        )

    @discord.ui.button(
        label="🗑️ Eliminar Favoritos",
        style=discord.ButtonStyle.danger,
        row=1,
    )
    async def delete_favorite(
        self,
        button: discord.ui.Button,
        interaction: discord.Interaction,
    ):
        favorites = get_favorites(interaction.user.id)

        if not favorites:
            await interaction.response.send_message(
                "📋 No tienes ninguna canción en favoritos.",
                ephemeral=True,
            )
            return

        # Resolver los títulos de los favoritos puede tardar más de 3 segundos.
        # Primero reconocemos la interacción para evitar "Unknown interaction".
        await interaction.response.defer(ephemeral=True)

        view = FavoriteSelectView(
            self.cog,
            self.guild_id,
            interaction.user.id,
            action="delete",
        )
        await view.load_page()

        await interaction.edit_original_response(
            content=view.page_message(),
            view=view,
        )


class FavoriteSelectView(discord.ui.View):
    PAGE_SIZE = 10

    def __init__(
        self,
        cog: "Music",
        guild_id: int,
        user_id: int,
        action: str,
    ):
        super().__init__(timeout=120)

        self.cog = cog
        self.guild_id = guild_id
        self.user_id = user_id
        self.action = action
        self.page = 0

        self.page_entries: list[dict] = []
        self.select: Optional[discord.ui.Select] = None

    @property
    def favorites(self) -> list[str]:
        return get_favorites(self.user_id)

    @property
    def total_pages(self) -> int:
        total = len(self.favorites)
        return max(1, math.ceil(total / self.PAGE_SIZE))

    def page_message(self) -> str:
        if self.action == "delete":
            title = "🗑️ **Eliminar Favoritos**"
            instruction = "Selecciona la canción que quieres eliminar:"
        else:
            title = "🎵 **Seleccionar Favoritos**"
            instruction = "Selecciona una canción para añadirla a la cola:"

        return (
            f"{title}\n"
            f"{instruction}\n"
            f"**Página {self.page + 1} de {self.total_pages}**"
        )

    async def _resolve_page(self) -> None:
        favorites = self.favorites

        if not favorites:
            self.page = 0
            self.page_entries = []
            return

        self.page = min(self.page, self.total_pages - 1)

        start = self.page * self.PAGE_SIZE
        end = min(start + self.PAGE_SIZE, len(favorites))

        self.page_entries = []

        for index in range(start, end):
            url = favorites[index]

            try:
                info = await self.cog._extract(url)
                title = (info.get("title") or "Sin título").strip()
                duration = info.get("duration")
                webpage_url = (
                    info.get("webpage_url")
                    or info.get("url")
                    or url
                )
                thumbnail = pick_thumbnail(info)
                uploader = info.get("artist") or info.get("uploader") or info.get("channel")
            except Exception:
                log.exception(
                    f"No se pudo obtener metadata del favorito {url!r} "
                    f"del usuario {self.user_id}"
                )
                title = "Favorito no disponible"
                duration = None
                webpage_url = url
                thumbnail = None
                uploader = None

            self.page_entries.append(
                {
                    "index": index,
                    "url": webpage_url,
                    "title": title,
                    "duration": duration,
                    "thumbnail": thumbnail,
                    "uploader": uploader,
                }
            )

    def _rebuild_components(self) -> None:
        # Conservamos únicamente los botones de paginación.
        for item in list(self.children):
            if isinstance(item, discord.ui.Select):
                self.remove_item(item)

        if self.page_entries:
            options = []

            for entry in self.page_entries:
                global_index = entry["index"]
                title = entry["title"] or "Sin título"
                label = f"{global_index + 1}. {title}"[:100]

                duration = entry.get("duration")
                description = (
                    format_duration(duration)
                    if duration
                    else "Duración desconocida"
                )[:100]

                options.append(
                    discord.SelectOption(
                        label=label,
                        description=description,
                        value=str(global_index),
                    )
                )

            self.select = discord.ui.Select(
                placeholder="Selecciona un favorito...",
                options=options,
                row=0,
            )
            self.select.callback = self.on_select
            self.add_item(self.select)
        else:
            self.select = None

        self.previous_button.disabled = self.page <= 0
        self.next_button.disabled = self.page >= self.total_pages - 1

    async def load_page(self) -> None:
        await self._resolve_page()
        self._rebuild_components()

    @discord.ui.button(
        label="⬅️ Anterior",
        style=discord.ButtonStyle.secondary,
        row=1,
    )
    async def previous_button(
        self,
        button: discord.ui.Button,
        interaction: discord.Interaction,
    ):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "❌ Este menú no te pertenece.",
                ephemeral=True,
            )
            return

        if self.page <= 0:
            await interaction.response.defer()
            return

        self.page -= 1
        await interaction.response.defer()
        await self.load_page()
        await interaction.edit_original_response(
            content=self.page_message(),
            view=self,
        )

    @discord.ui.button(
        label="➡️ Siguiente",
        style=discord.ButtonStyle.secondary,
        row=1,
    )
    async def next_button(
        self,
        button: discord.ui.Button,
        interaction: discord.Interaction,
    ):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "❌ Este menú no te pertenece.",
                ephemeral=True,
            )
            return

        if self.page >= self.total_pages - 1:
            await interaction.response.defer()
            return

        self.page += 1
        await interaction.response.defer()
        await self.load_page()
        await interaction.edit_original_response(
            content=self.page_message(),
            view=self,
        )

    async def on_select(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "❌ Este menú no te pertenece.",
                ephemeral=True,
            )
            return

        favorites = self.favorites
        if not favorites:
            self.stop()
            await interaction.response.edit_message(
                content="📋 Ya no tienes ninguna canción en favoritos.",
                view=None,
            )
            return

        index = int(self.select.values[0])

        if index < 0 or index >= len(favorites):
            await interaction.response.send_message(
                "❌ Ese favorito ya no existe.",
                ephemeral=True,
            )
            return

        entry = next(
            (item for item in self.page_entries if item["index"] == index),
            None,
        )

        if entry is None:
            await self.load_page()
            entry = next(
                (item for item in self.page_entries if item["index"] == index),
                None,
            )

        if entry is None:
            await interaction.response.send_message(
                "❌ No pude cargar ese favorito. Inténtalo nuevamente.",
                ephemeral=True,
            )
            return

        title = entry["title"]
        url = entry["url"]

        if self.action == "play":
            state = self.cog.get_state(self.guild_id)

            if not state.voice_client or not state.voice_client.is_connected():
                await interaction.response.send_message(
                    "❌ El bot ya no está conectado al canal de voz.",
                    ephemeral=True,
                )
                return

            state.text_channel = interaction.channel
            song = Song(
                title=title,
                webpage_url=url,
                duration=entry.get("duration"),
                requester=interaction.user.display_name,
                thumbnail=entry.get("thumbnail"),
                uploader=entry.get("uploader"),
            )
            state.queue.append(song)

            self.stop()
            await interaction.response.edit_message(
                content=f"⭐ **{title}** fue añadida a la cola.",
                view=None,
            )
            return

        # La reconstrucción de la página vuelve a consultar metadata con yt-dlp,
        # así que reconocemos primero la interacción.
        await interaction.response.defer()

        removed = remove_favorite(self.user_id, index)

        if removed is None:
            await interaction.edit_original_response(
                content="❌ No pude eliminar ese favorito.",
                view=self,
            )
            return

        # Recalcular la página por si acabamos de borrar el último elemento.
        if self.page > 0 and self.page >= self.total_pages:
            self.page = self.total_pages - 1

        if not self.favorites:
            self.stop()
            await interaction.edit_original_response(
                content=f"🗑️ **{title}** fue eliminado de tus favoritos.\n\n"
                "📋 Ya no tienes favoritos guardados.",
                view=None,
            )
            return

        await self.load_page()
        await interaction.edit_original_response(
            content=f"🗑️ **{title}** fue eliminado de tus favoritos.\n\n"
            f"{self.page_message()}",
            view=self,
        )

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


class MusicControls(discord.ui.View):
    LOOP_LABELS = {
        "off": "🔁 Repetir: Off",
        "song": "🔂 Repetir: Canción",
        "queue": "🔁 Repetir: Cola",
    }
    LOOP_ORDER = ["off", "song", "queue"]

    def __init__(self, cog: "Music", guild_id: int):
        super().__init__(timeout=None)
        self.cog = cog
        self.guild_id = guild_id
        state = self.cog.get_state(guild_id)
        self.loop_button.label = self.LOOP_LABELS[state.loop_mode]

    @discord.ui.button(label="⏸️ Pausar", style=discord.ButtonStyle.primary, row=0)
    async def pause_resume(self, button: discord.ui.Button, interaction: discord.Interaction):
        state = self.cog.get_state(self.guild_id)
        if not state.voice_client:
            await interaction.response.send_message("No estoy en un canal de voz.", ephemeral=True)
            return
        if state.voice_client.is_playing():
            state.voice_client.pause()
            state.mark_paused()
            button.label = "▶️ Reanudar"
            button.style = discord.ButtonStyle.success
            await interaction.response.edit_message(view=self)
        elif state.voice_client.is_paused():
            state.voice_client.resume()
            state.mark_resumed()
            button.label = "⏸️ Pausar"
            button.style = discord.ButtonStyle.primary
            await interaction.response.edit_message(view=self)
        else:
            await interaction.response.send_message("No hay nada reproduciéndose.", ephemeral=True)

    @discord.ui.button(label="⏭️ Saltar", style=discord.ButtonStyle.primary, row=0)
    async def skip(self, button: discord.ui.Button, interaction: discord.Interaction):
        state = self.cog.get_state(self.guild_id)
        if state.voice_client and (state.voice_client.is_playing() or state.voice_client.is_paused()):
            state.skip_song_loop_once = True
            state.voice_client.stop()
            await interaction.response.send_message("⏭️ Canción saltada.", ephemeral=True)
        else:
            await interaction.response.send_message("No hay nada sonando ahora mismo.", ephemeral=True)

    @discord.ui.button(label="⏹️ Detener", style=discord.ButtonStyle.danger, row=0)
    async def stop(self, button: discord.ui.Button, interaction: discord.Interaction):
        state = self.cog.get_state(self.guild_id)
        state.queue.clear()
        state.active_playlist = None
        state.suppress_requeue = True
        if state.voice_client and (state.voice_client.is_playing() or state.voice_client.is_paused()):
            state.voice_client.stop()
        await interaction.response.send_message("⏹️ Detenido y cola vaciada.", ephemeral=True)
    
    @discord.ui.button(
    label="🗑️ Eliminar playlist",
    style=discord.ButtonStyle.danger,
    row=1
)
    async def delete_playlist(self, button: discord.ui.Button, interaction: discord.Interaction):
        state = self.cog.get_state(self.guild_id)

        if state.active_playlist is None:
            await interaction.response.send_message(
                "ℹ️ No hay ninguna playlist activa.",
                ephemeral=True
            )
            return

        playlist_name = state.active_playlist.get("title", "Playlist")

        # Cancelar la playlist en segundo plano
        state.active_playlist = None

        await interaction.response.send_message(
            f"🗑️ Playlist **{playlist_name}** eliminada. Las canciones en cola se mantienen.",
            ephemeral=True
        )    

    @discord.ui.button(label="📜 Lista", style=discord.ButtonStyle.secondary, row=0)
    async def show_queue(self, button: discord.ui.Button, interaction: discord.Interaction):
        state = self.cog.get_state(self.guild_id)
        await interaction.response.send_message(format_queue_text(state))

    @discord.ui.button(label="🔁 Repetir: Off", style=discord.ButtonStyle.secondary, row=1)
    async def loop_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        state = self.cog.get_state(self.guild_id)
        idx = self.LOOP_ORDER.index(state.loop_mode)
        state.loop_mode = self.LOOP_ORDER[(idx + 1) % len(self.LOOP_ORDER)]
        button.label = self.LOOP_LABELS[state.loop_mode]
        if state.current:
            embed = build_now_playing_embed(state.current, state.get_elapsed(), state.loop_mode)
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            await interaction.response.edit_message(view=self)

    @discord.ui.button(label="🔀 Mezclar", style=discord.ButtonStyle.secondary, row=1)
    async def shuffle_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        state = self.cog.get_state(self.guild_id)
        if len(state.queue) < 2:
            await interaction.response.send_message(
                "No hay suficientes canciones en la cola para mezclar.", ephemeral=True
            )
            return
        items = list(state.queue)
        random.shuffle(items)
        state.queue = deque(items)
        await interaction.response.send_message(f"🔀 Mezclé {len(items)} canciones en la cola.", ephemeral=True)

    @discord.ui.button(label="🕘 Historial", style=discord.ButtonStyle.secondary, row=1)
    async def history_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        state = self.cog.get_state(self.guild_id)
        if not state.history:
            await interaction.response.send_message("Todavía no sonó nada en esta sesión.", ephemeral=True)
            return
        view = HistoryView(self.cog, self.guild_id, interaction.user.id, state.history)
        await interaction.response.send_message(
            f"🕘 Últimas {len(view.entries)} canciones de esta sesión, elegí una:",
            view=view,
            ephemeral=True,
        )

    @discord.ui.button(label="⭐ Favoritos", style=discord.ButtonStyle.secondary, row=1)
    async def favorites_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        view = FavoritesMenuView(self.cog, self.guild_id)
        await interaction.response.send_message(
            "⭐ **Favoritos**\n¿Qué quieres hacer?",
            view=view,
            ephemeral=True,
        )

    @discord.ui.button(label="📜 Letra", style=discord.ButtonStyle.secondary, row=2)
    async def lyrics_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        if not genius_configured():
            await interaction.response.send_message(
                "La búsqueda de letras no está configurada en este bot. "
                "Hace falta agregar `GENIUS_ACCESS_TOKEN` al `.env`.",
                ephemeral=True,
            )
            return

        state = self.cog.get_state(self.guild_id)
        if not state.current:
            await interaction.response.send_message(
                "No hay ninguna canción sonando ahora mismo.", ephemeral=True
            )
            return

        await interaction.response.defer()
        await self.cog.send_lyrics(
            interaction.followup.send,
            state.current.title,
            artist_hint=state.current.uploader,
            song_key=state.current.webpage_url,
        )


class SearchResultsView(discord.ui.View):
    def __init__(self, cog: "Music", guild: discord.Guild, author: discord.Member,
                 text_channel: discord.abc.Messageable, results: list[dict]):
        super().__init__(timeout=60)
        self.cog = cog
        self.guild = guild
        self.author = author
        self.text_channel = text_channel
        self.results = results[:5]

        options = []
        for i, r in enumerate(self.results):
            title = (r.get("title") or "Sin título")[:100]
            duration = r.get("duration")
            desc = format_duration(duration) if duration else "Duración desconocida"
            options.append(discord.SelectOption(label=title, description=desc, value=str(i)))

        self.select = discord.ui.Select(placeholder="Elegí un resultado...", options=options)
        self.select.callback = self.on_select
        self.add_item(self.select)

    async def on_select(self, interaction: discord.Interaction):
        if interaction.user.id != self.author.id:
            await interaction.response.send_message(
                "Solo quien hizo la búsqueda puede elegir un resultado.", ephemeral=True
            )
            return

        await interaction.response.defer()
        idx = int(self.select.values[0])
        entry = self.results[idx]
        title = entry.get("title") or "Sin título"
        video_id = entry.get("id")
        webpage_url = (
            entry.get("webpage_url")
            or (f"https://www.youtube.com/watch?v={video_id}" if video_id else entry.get("url"))
        )
        duration = entry.get("duration")
        thumbnail = pick_thumbnail(entry)

        _, msg = await self.cog.handle_play_request(
            self.guild,
            interaction.user,
            self.text_channel,
            title,
            webpage_url,
            duration,
            thumbnail,
            entry.get("uploader") or entry.get("channel"),
        )

        await self.text_channel.send(msg)

        try:
            await interaction.delete_original_response()
        except discord.HTTPException:
            pass
        self.stop()


class HistoryView(discord.ui.View):
    def __init__(self, cog: "Music", guild_id: int, author_id: int, history_songs: list["Song"]):
        super().__init__(timeout=60)
        self.cog = cog
        self.guild_id = guild_id
        self.author_id = author_id

        unique_songs = []
        seen_urls = set()

        for song in reversed(history_songs):
            if song.webpage_url not in seen_urls:
                seen_urls.add(song.webpage_url)
                unique_songs.append(song)

        self.entries = unique_songs[:25]

        options = []
        for i, song in enumerate(self.entries):
            title = song.title[:100]
            desc = format_duration(song.duration) if song.duration else "Duración desconocida"
            options.append(discord.SelectOption(label=title, description=desc, value=str(i)))

        self.select = discord.ui.Select(placeholder="Elegí una canción del historial...", options=options)
        self.select.callback = self.on_select
        self.add_item(self.select)

    async def on_select(self, interaction: discord.Interaction):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "Solo quien pidió el historial puede elegir acá.", ephemeral=True
            )
            return

        idx = int(self.select.values[0])
        song = self.entries[idx]

        state = self.cog.get_state(self.guild_id)
        state.queue.appendleft(song)

        for item in self.children:
            item.disabled = True
        try:
            await interaction.response.edit_message(
                content=f"⏮️ **{song.title}** va a sonar apenas termine la actual.",
                view=self,
            )
        except discord.HTTPException:
            pass
        self.stop()

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


class GuildMusicState:
    def __init__(self, cog: "Music", bot: commands.Bot, guild_id: int):
        self.cog = cog
        self.bot = bot
        self.guild_id = guild_id
        self.queue: deque[Song] = deque()
        self.voice_client: Optional[discord.VoiceClient] = None
        self.current: Optional[Song] = None
        self.current_processes: tuple[subprocess.Popen, subprocess.Popen] = ()
        self.volume: float = get_guild_volume(guild_id)
        self.play_next_event = asyncio.Event()
        self.player_task = bot.loop.create_task(self._player_loop())
        self.text_channel: Optional[discord.abc.Messageable] = None

        self.loop_mode: str = "off"
        self.suppress_requeue: bool = False
        self.skip_song_loop_once: bool = False

        self.now_playing_msg: Optional[discord.Message] = None
        self.playback_started_at: Optional[float] = None
        self.pause_started_at: Optional[float] = None
        self.total_paused_seconds: float = 0.0
        self.progress_task: Optional[asyncio.Task] = None

        self.empty_since: Optional[float] = None

        self.history: list[Song] = []
        self.active_playlist: Optional[dict] = None

    def mark_paused(self):
        if self.pause_started_at is None:
            self.pause_started_at = time.monotonic()

    def mark_resumed(self):
        if self.pause_started_at is not None:
            self.total_paused_seconds += time.monotonic() - self.pause_started_at
            self.pause_started_at = None

    def get_elapsed(self) -> float:
        if self.playback_started_at is None:
            return 0.0
        now = time.monotonic()
        paused_extra = (now - self.pause_started_at) if self.pause_started_at else 0.0
        return max(0.0, now - self.playback_started_at - self.total_paused_seconds - paused_extra)

    async def _update_progress_loop(self):
        try:
            while True:
                await asyncio.sleep(5)
                if not self.now_playing_msg or not self.current:
                    return
                if not (self.voice_client and (self.voice_client.is_playing() or self.voice_client.is_paused())):
                    return
                embed = build_now_playing_embed(self.current, self.get_elapsed(), self.loop_mode)
                try:
                    await self.now_playing_msg.edit(embed=embed)
                except discord.HTTPException:
                    return
        except asyncio.CancelledError:
            pass

    async def _player_loop(self):
        await self.bot.wait_until_ready()
        while True:
            self.play_next_event.clear()

            if self.current is not None and not self.suppress_requeue:
                if self.loop_mode == "queue":
                    self.queue.append(self.current)
                elif self.loop_mode == "song" and not self.skip_song_loop_once:
                    self.queue.appendleft(self.current)
            self.suppress_requeue = False
            self.skip_song_loop_once = False

            if self.voice_client is None or not self.voice_client.is_connected():
                # No tocamos la cola ni la playlist activa mientras la voz
                # esté caída, así no se pierde nada: apenas se reconecte,
                # seguimos exactamente donde estábamos.
                await asyncio.sleep(1)
                continue

            if not self.queue and self.active_playlist:
                pl = self.active_playlist
                while pl["current_index"] < len(pl["entries"]):
                    entry = pl["entries"][pl["current_index"]]
                    pl["current_index"] += 1
                    
                    if not entry:
                        continue
                        
                    video_id = entry.get("id")
                    raw_url = entry.get("url")

                    if video_id:
                        # Prioridad al ID: con extracción completa (Mixes),
                        # entry["url"] puede ser directamente la URL del
                        # stream de audio (de Google, con vencimiento corto)
                        # en vez de la página del video — no sirve para
                        # volver a resolverla más adelante.
                        webpage_url = f"https://www.youtube.com/watch?v={video_id}"
                    elif raw_url and raw_url.startswith("/"):
                        webpage_url = f"https://www.youtube.com{raw_url}"
                    elif raw_url and raw_url.startswith("http"):
                        webpage_url = raw_url
                    else:
                        webpage_url = None

                    if not webpage_url:
                        continue
                        
                    # Como ahora forzamos la extracción pura, yt-dlp sí nos da el título real
                    title = entry.get("title") or entry.get("name") or "Sin título"
                    
                    # Respaldo súper ligero por si algún video oculto sigue dando problemas
                    if title == "Sin título":
                        try:
                            full_info = await self.cog._extract(webpage_url)
                            title = full_info.get("title") or "Sin título"
                        except Exception:
                            pass
                            
                    song = Song(
                        title=title,
                        webpage_url=webpage_url,
                        duration=entry.get("duration"),
                        requester=f"{pl['requester']}",
                        thumbnail=pick_thumbnail(entry),
                        uploader=entry.get("uploader") or entry.get("channel"),
                    )
                    self.queue.append(song) # Metemos solo la que sigue y rompemos el ciclo
                    break
                
                # Si llegamos al final de la playlist, la borramos
                if pl["current_index"] >= len(pl["entries"]):
                    self.active_playlist = None

            # CÓDIGO EXISTENTE:
            try:
                self.current = self.queue.popleft()
            except IndexError:
                self.current = None
                await asyncio.sleep(1)
                continue

            if self.voice_client is None or not self.voice_client.is_connected():
                await asyncio.sleep(1)
                continue

            preparing_msg = None
            if self.text_channel:
                preparing_msg = await self.text_channel.send(
                    f"🔄 Preparando: **{self.current.title}**..."
                )

            loop = asyncio.get_event_loop()
            try:
                ytdlp_proc, ffmpeg_proc = await loop.run_in_executor(
                    None, spawn_playback_pipeline, self.current.webpage_url
                )
            except Exception:
                log.exception("No se pudo lanzar el pipeline de audio")
                if preparing_msg:
                    await preparing_msg.edit(
                        content=f"⚠️ No se pudo preparar **{self.current.title}**, la salteo."
                    )
                continue

            self.current_processes = (ytdlp_proc, ffmpeg_proc)
            source = BufferedPCMSource(ffmpeg_proc.stdout)

            await loop.run_in_executor(None, source.wait_until_ready, 20.0)

            source = discord.PCMVolumeTransformer(source, volume=self.volume)

            def _after(error, guild_id=self.guild_id, procs=(ytdlp_proc, ffmpeg_proc)):
                if error:
                    log.error(f"Error en reproducción (guild {guild_id}): {error}")
                for p in procs:
                    if p.poll() is None:
                        p.terminate()
                if self.progress_task:
                    self.bot.loop.call_soon_threadsafe(self.progress_task.cancel)
                self.bot.loop.call_soon_threadsafe(self.play_next_event.set)

            self.voice_client.play(source, after=_after)

            self.playback_started_at = time.monotonic()
            self.pause_started_at = None
            self.total_paused_seconds = 0.0

            self.history = [s for s in self.history if s.webpage_url != self.current.webpage_url]
            self.history.append(self.current)
            if len(self.history) > MAX_HISTORY:
                self.history = self.history[-MAX_HISTORY:]

            embed = build_now_playing_embed(self.current, 0, self.loop_mode)
            view = MusicControls(self.cog, self.guild_id)
            if preparing_msg:
                await preparing_msg.edit(content=None, embed=embed, view=view)
                self.now_playing_msg = preparing_msg
            elif self.text_channel:
                self.now_playing_msg = await self.text_channel.send(embed=embed, view=view)

            if self.progress_task:
                self.progress_task.cancel()
            self.progress_task = self.bot.loop.create_task(self._update_progress_loop())

            await self.play_next_event.wait()

    def cleanup(self):
        self.player_task.cancel()
        if self.progress_task:
            self.progress_task.cancel()
        for p in self.current_processes:
            if p and p.poll() is None:
                p.terminate()


class Music(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.states: dict[int, GuildMusicState] = {}

    def get_state(self, guild_id: int) -> GuildMusicState:
        if guild_id not in self.states:
            self.states[guild_id] = GuildMusicState(self, self.bot, guild_id)
        return self.states[guild_id]

    async def _safe_respond(self, ctx: discord.ApplicationContext, content: str, **kwargs):
        """Igual que ctx.respond(), pero si el token de la interacción ya
        expiró (playlists grandes que tardan en extraerse pueden hacer que
        pase), manda el mensaje directo al canal en vez de tirar un error
        sin avisarle nada al usuario."""
        try:
            return await ctx.respond(content, **kwargs)
        except (discord.NotFound, discord.HTTPException):
            log.warning("No pude responder a la interacción (probablemente expiró), mando al canal directo.")
            try:
                return await ctx.channel.send(content, **kwargs)
            except Exception:
                log.exception("Tampoco pude mandar el mensaje directo al canal.")
                return None

    async def _extract(self, query: str) -> dict:
        loop = asyncio.get_event_loop()

        def _run():
            info = ytdl.extract_info(query, download=False, process=False)
            if "entries" in info:
                info = next(iter(info["entries"]))
            return info

        info = await loop.run_in_executor(None, _run)
        return info

    async def _search(self, query: str, n: int = 5) -> list[dict]:
        loop = asyncio.get_event_loop()

        def _run():
            search_opts = dict(YTDL_OPTS)
            search_opts["extract_flat"] = True
            search_opts["noplaylist"] = False
            
            # Eliminamos default_search y source_address para evitar conflictos
            search_opts.pop("default_search", None)
            search_opts.pop("source_address", None)
            
            # Forzamos a yt-dlp a que use el motor de búsqueda explícitamente
            search_query = f"ytsearch{n}:{query}"
            
            with yt_dlp.YoutubeDL(search_opts) as searcher:
                info = searcher.extract_info(search_query, download=False)
            
            if not info:
                return []
                
            # yt-dlp suele devolver un diccionario con la clave 'entries' en las búsquedas
            if "entries" in info:
                return list(info["entries"])
            
            # Como plan B, por si devuelve un único resultado sin meterlo en 'entries'
            return [info]

        return await loop.run_in_executor(None, _run)
    
    async def _extract_playlist(
        self, url: str, flat: bool = True, playlistend: Optional[int] = None,
        player_client: Optional[list[str]] = None,
    ) -> dict:
        loop = asyncio.get_event_loop()
        def _run():
            opts = dict(YTDL_OPTS)
            opts["extract_flat"] = flat
            opts["noplaylist"] = False
            opts.pop("default_search", None)
            if playlistend:
                opts["playlistend"] = playlistend
            if player_client:
                opts["extractor_args"] = {"youtube": {"player_client": player_client}}
            with yt_dlp.YoutubeDL(opts) as ydl:
                return ydl.extract_info(url, download=False)
        return await loop.run_in_executor(None, _run)

    async def handle_play_request(
        self,
        guild: discord.Guild,
        member: discord.Member,
        text_channel: discord.abc.Messageable,
        title: str,
        webpage_url: str,
        duration: Optional[int],
        thumbnail: Optional[str],
        uploader: Optional[str] = None,
    ) -> tuple[Optional[Song], str]:
        if member.voice is None or member.voice.channel is None:
            return None, "Tenés que estar en un canal de voz primero."

        state = self.get_state(guild.id)
        state.text_channel = text_channel

        voice_channel = member.voice.channel
        
        # --- SOLUCIÓN: Revisar guild.voice_client en lugar de solo state.voice_client ---
        if guild.voice_client is None or not guild.voice_client.is_connected():
            # Si el bot realmente no está en ningún canal, lo conectamos
            state.voice_client = await voice_channel.connect()
            state.history = []
        else:
            # Si ya está conectado (incluso si se nos reinició el código), recuperamos la sesión
            state.voice_client = guild.voice_client
            # Y si está en un canal distinto al del usuario, lo movemos
            if state.voice_client.channel.id != voice_channel.id:
                await state.voice_client.move_to(voice_channel)
        # --------------------------------------------------------------------------------

        song = Song(
            title=title,
            webpage_url=webpage_url,
            duration=duration,
            requester=member.display_name,
            thumbnail=thumbnail,
            uploader=uploader,
        )
        was_playing = state.current is not None
        state.queue.append(song)

        msg = f"➕ Agregado a la cola: **{song.title}**" if was_playing else f"✅ Cargado: **{song.title}**"
        return song, msg

    async def _resolve_spotify_track_to_youtube(self, track: dict) -> Optional[dict]:
        primary_artist = (track.get("artists") or "").split(",")[0].strip()
        search_query = f"{primary_artist} - {track['title']}" if primary_artist else track["title"]
        try:
            results = await self._search(search_query, n=1)
        except Exception:
            log.exception(f"Error buscando en YouTube: {search_query!r}")
            return None
        if not results:
            log.error(f"Búsqueda en YouTube sin resultados para: {search_query!r} (track={track!r})")
            return None
        return results[0]

    async def _handle_spotify(self, ctx: discord.ApplicationContext, spotify_match: tuple[str, str]):
        kind, item_id = spotify_match

        if kind in ("album", "playlist") and not spotify_configured():
            await ctx.respond(
                "Álbumes y playlists de Spotify necesitan credenciales configuradas en el bot "
                "(`SPOTIFY_CLIENT_ID`/`SPOTIFY_CLIENT_SECRET`, y la cuenta que creó esa app tiene "
                "que tener Spotify Premium). Canciones sueltas sí funcionan sin nada de eso."
            )
            return

        if ctx.author.voice is None or ctx.author.voice.channel is None:
            await ctx.respond("Tenés que estar en un canal de voz primero.")
            return

        await ctx.defer()

        loop = asyncio.get_event_loop()
        try:
            tracks = await loop.run_in_executor(None, fetch_spotify_tracks, kind, item_id)
        except Exception:
            log.exception("Error consultando Spotify")
            await ctx.respond("No pude leer ese link de Spotify. Revisá que sea público y válido.")
            return

        if not tracks:
            await ctx.respond("No encontré canciones en ese link de Spotify.")
            return

        if kind == "track":
            entry = await self._resolve_spotify_track_to_youtube(tracks[0])
            if not entry:
                await ctx.respond(f"No encontré **{tracks[0]['title']}** en YouTube.")
                return
            video_id = entry.get("id")
            webpage_url = entry.get("webpage_url") or (
                f"https://www.youtube.com/watch?v={video_id}" if video_id else entry.get("url")
            )
            _, msg = await self.handle_play_request(
                ctx.guild,
                ctx.author,
                ctx.channel,
                entry.get("title") or tracks[0]["title"],
                webpage_url,
                entry.get("duration"),
                pick_thumbnail(entry),
            )
            await ctx.respond(f"🎧 Desde Spotify: {msg}")
            return

        await ctx.respond(
            f"🎧 Encontré {len(tracks)} canciones en Spotify, buscándolas en YouTube y "
            f"encolando (puede tardar según cuántas sean)..."
        )

        added = 0
        failed = 0
        for track in tracks:
            entry = await self._resolve_spotify_track_to_youtube(track)
            if not entry:
                failed += 1
                continue
            video_id = entry.get("id")
            webpage_url = entry.get("webpage_url") or (
                f"https://www.youtube.com/watch?v={video_id}" if video_id else entry.get("url")
            )
            try:
                await self.handle_play_request(
                    ctx.guild,
                    ctx.author,
                    ctx.channel,
                    entry.get("title") or track["title"],
                    webpage_url,
                    entry.get("duration"),
                    pick_thumbnail(entry),
                )
                added += 1
            except Exception:
                log.exception("Error encolando canción de Spotify")
                failed += 1

        summary = f"✅ Encolé {added} canciones desde Spotify."
        if failed:
            summary += f" No pude encontrar {failed} en YouTube."
        await ctx.channel.send(summary)

    @commands.slash_command(name="play", description="Reproduce audio desde un link de YouTube/YT Music/Spotify, o buscá por nombre")
    async def play(
        self,
        ctx: discord.ApplicationContext,
        query: Option(str, "Link de YouTube/YT Music/Spotify, o el nombre de lo que querés buscar"),
    ):
        # 1. Manejo de Spotify
        spotify_match = parse_spotify_url(query) if "open.spotify.com" in query else None
        if spotify_match:
            await self._handle_spotify(ctx, spotify_match)
            return

        is_url = query.startswith("http://") or query.startswith("https://")

        if is_url:
            await ctx.defer()

            # 2. NUEVO: Detectar si es un enlace de lista de YouTube (Lazy Loading)
            playlist_ready = False
            playlist_state = None
            if "list=" in query and ("youtube.com" in query or "youtu.be" in query):
                try:
                    import urllib.parse
                    parsed = urllib.parse.urlparse(query)
                    qs = urllib.parse.parse_qs(parsed.query)

                    # Los Mixes de YouTube (list=RDxxxxx) no tienen una
                    # página de playlist real en /playlist?list=... — solo
                    # existen dentro de la URL del video semilla
                    # (watch?v=...&list=RDxxxx). Si forzamos la URL "limpia"
                    # de playlist para un Mix, yt-dlp no puede resolverlo y
                    # termina tratándolo como video suelto. Las playlists
                    # normales (list=PLxxxx) sí se benefician de la URL
                    # limpia, así que solo la forzamos en ese caso.
                    list_id = qs.get("list", [None])[0]
                    is_mix = bool(list_id) and list_id.startswith("RD")

                    clean_url = query
                    if list_id and not is_mix:
                        clean_url = f"https://www.youtube.com/playlist?list={list_id}"

                    # La extracción completa (no flat) para Mixes era
                    # demasiado lenta (resuelve cada video entero, JS
                    # challenge incluido, uno por uno). Volvemos al modo
                    # rápido, pero forzando el cliente "web" para Mixes: el
                    # desorden salía porque nuestro forzado normal de
                    # clientes móviles (android/ios/mweb, usado para evitar
                    # otro bloqueo al reproducir) arma una secuencia de Mix
                    # distinta a la que ves en el navegador, que usa "web".
                    info = await self._extract_playlist(
                        clean_url,
                        flat=True,
                        player_client=["web"] if is_mix else None,
                    )
                    entries = info.get("entries")
                    
                    if entries:
                        entries = list(entries)
                        state = self.get_state(ctx.guild.id)

                        if ctx.author.voice is None or ctx.author.voice.channel is None:
                            await self._safe_respond(ctx, "Tenés que estar en un canal de voz primero.")
                            return

                        voice_channel = ctx.author.voice.channel

                        if ctx.guild.voice_client is None or not ctx.guild.voice_client.is_connected():
                            state.voice_client = await voice_channel.connect()
                            state.history = []
                        else:
                            state.voice_client = ctx.guild.voice_client
                            if state.voice_client.channel.id != voice_channel.id:
                                await state.voice_client.move_to(voice_channel)

                        state.text_channel = ctx.channel

                        # Buscar si el link traía un video específico para empezar desde ahí
                        start_index = 0
                        if "v" in qs:
                            target_v = qs["v"][0]
                            for i, e in enumerate(entries):
                                if e and (e.get("id") == target_v or target_v in (e.get("url") or "")):
                                    start_index = i
                                    break

                        state.active_playlist = {
                            "title": info.get("title", "Lista de reproducción"),
                            "entries": entries,
                            "current_index": start_index,
                            "requester": ctx.author.display_name
                        }
                        playlist_ready = True
                        playlist_state = state.active_playlist

                except Exception as e:
                    log.exception("Fallo al extraer playlist, procediendo como video único.")

            if playlist_ready:
                # Separado del try/except de arriba a propósito: si esto
                # falla (ej. la interacción ya expiró por una playlist que
                # tardó mucho en extraerse), NO queremos que caiga al bloque
                # de "video único" de abajo, porque la playlist ya quedó
                # armada y sonando: procesarla de nuevo la duplicaría.
                await self._safe_respond(
                    ctx,
                    f"🎶 Playlist cargada en segundo plano: **{playlist_state['title']}** "
                    f"({len(playlist_state['entries'])} canciones).\n"
                    f"*(Se irá añadiendo de a una. Si piden una canción suelta, se tocará primero y luego se retomará la lista).*"
                )
                return

            # 3. Manejo de URL individual (o fallback de playlist fallida)
            try:
                info = await self._extract(query)
            except Exception as e:
                log.exception("Error extrayendo metadata")
                await self._safe_respond(ctx, f"No pude procesar ese link: `{e}`")
                return

            _, msg = await self.handle_play_request(
                ctx.guild,
                ctx.author,
                ctx.channel,
                info.get("title", "Sin título"),
                info.get("webpage_url") or info.get("url") or query,
                info.get("duration"),
                pick_thumbnail(info),
                info.get("artist") or info.get("uploader") or info.get("channel"),
            )
            await self._safe_respond(ctx, msg)
            return

        # 4. Manejo de búsqueda por nombre
        await ctx.defer(ephemeral=True)
        try:
            results = await self._search(query)
        except Exception:
            log.exception("Error buscando en YouTube")
            await ctx.respond("No pude buscar eso, intentá de nuevo.")
            return

        if not results:
            await ctx.respond(f"No encontré resultados para **{query}**.")
            return

        view = SearchResultsView(self, ctx.guild, ctx.author, ctx.channel, results)
        await ctx.respond(f"Resultados para **{query}**, elegí uno:", view=view)    

    async def send_lyrics(
        self,
        send,
        raw_title: str,
        artist_hint: Optional[str] = None,
        song_key: Optional[str] = None,
    ):
        """Busca la letra y la manda usando `send` (que puede ser
        `ctx.followup.send` o `interaction.followup.send`).

        Si no hay una coincidencia confiable NO manda una letra cualquiera:
        muestra el menú para que el usuario elija la canción correcta."""
        loop = asyncio.get_event_loop()
        try:
            result = await loop.run_in_executor(
                None, resolve_lyrics, raw_title, artist_hint, song_key
            )
        except Exception:
            log.exception(f"Error buscando letra de: {raw_title!r}")
            await send(
                "No pude buscar la letra ahora mismo (falló la búsqueda). "
                "Probá de nuevo en un rato."
            )
            return

        if result["status"] == "not_found":
            await send(
                f"No encontré la letra de **{raw_title}**.\n"
                f"Probá con `/lyrics artista - canción` escribiendo el nombre exacto."
            )
            return

        if result["status"] == "ambiguous":
            await send(
                content=(
                    f"🤔 No estoy seguro de cuál es la letra de **{raw_title}**: "
                    f"hay varias canciones parecidas. Elegí la correcta 👇"
                ),
                view=LyricsPickerView(result["candidates"], song_key),
            )
            return

        song = result["song"]
        others = [c for c in result["candidates"] if c["url"] != song["url"]]
        embeds = build_lyrics_embeds(song, result["lyrics"])
        for i, embed in enumerate(embeds):
            if i == 0:
                await send(embed=embed, view=LyricsCorrectionView(others, song_key))
            else:
                await send(embed=embed)

    @commands.slash_command(
        name="lyrics",
        description="Muestra la letra de lo que está sonando, o de la canción que le pidas",
    )
    async def lyrics_cmd(
        self,
        ctx: discord.ApplicationContext,
        busqueda: Option(
            str,
            "Artista y canción (si lo dejás vacío, usa la que está sonando)",
            required=False,
        ) = None,
    ):
        if not genius_configured():
            await ctx.respond(
                "La búsqueda de letras no está configurada en este bot. "
                "Hace falta agregar `GENIUS_ACCESS_TOKEN` al `.env`.",
                ephemeral=True,
            )
            return

        if not busqueda:
            state = self.get_state(ctx.guild.id)
            if not state.current:
                await ctx.respond(
                    "No hay nada sonando. Pasame el nombre: `/lyrics artista - canción`.",
                    ephemeral=True,
                )
                return
            await ctx.defer()
            await self.send_lyrics(
                ctx.followup.send,
                state.current.title,
                artist_hint=state.current.uploader,
                song_key=state.current.webpage_url,
            )
            return

        await ctx.defer()
        await self.send_lyrics(ctx.followup.send, busqueda)

    @commands.slash_command(name="skip", description="Salta la canción actual")
    async def skip(self, ctx: discord.ApplicationContext):
        state = self.get_state(ctx.guild.id)
        if state.voice_client and (state.voice_client.is_playing() or state.voice_client.is_paused()):
            state.skip_song_loop_once = True
            state.voice_client.stop()
            await ctx.respond("⏭️ Saltada.")
        else:
            await ctx.respond("No hay nada sonando ahora mismo.")

    @commands.slash_command(name="pause", description="Pausa la reproducción")
    async def pause(self, ctx: discord.ApplicationContext):
        state = self.get_state(ctx.guild.id)
        if state.voice_client and state.voice_client.is_playing():
            state.voice_client.pause()
            state.mark_paused()
            await ctx.respond("⏸️ Pausado.")
        else:
            await ctx.respond("No hay nada reproduciéndose.")

    @commands.slash_command(name="resume", description="Reanuda la reproducción")
    async def resume(self, ctx: discord.ApplicationContext):
        state = self.get_state(ctx.guild.id)
        if state.voice_client and state.voice_client.is_paused():
            state.voice_client.resume()
            state.mark_resumed()
            await ctx.respond("▶️ Reanudado.")
        else:
            await ctx.respond("No hay nada pausado.")

    @commands.slash_command(name="stop", description="Detiene todo y limpia la cola")
    async def stop(self, ctx: discord.ApplicationContext):
        state = self.get_state(ctx.guild.id)
        state.queue.clear()
        state.active_playlist = None
        state.suppress_requeue = True
        if state.voice_client and (state.voice_client.is_playing() or state.voice_client.is_paused()):
            state.voice_client.stop()
        await ctx.respond("⏹️ Detenido y cola vaciada.")

    @commands.slash_command(name="leave", description="Saca al bot del canal de voz")
    async def leave(self, ctx: discord.ApplicationContext):
        state = self.get_state(ctx.guild.id)
        state.queue.clear()
        state.active_playlist = None
        state.suppress_requeue = True
        state.history = []
        if state.voice_client:
            await state.voice_client.disconnect()
            state.voice_client = None
        await ctx.respond("👋 Listo, salí del canal.")

    @commands.slash_command(name="queue", description="Muestra la cola de reproducción")
    async def queue_cmd(self, ctx: discord.ApplicationContext):
        state = self.get_state(ctx.guild.id)
        await ctx.respond(format_queue_text(state))

    @commands.slash_command(name="volume", description="Cambia el volumen (0-100)")
    async def volume(self, ctx: discord.ApplicationContext, nivel: Option(int, "Volumen de 0 a 100")):
        if not 0 <= nivel <= 100:
            await ctx.respond("El nivel tiene que estar entre 0 y 100.")
            return
        state = self.get_state(ctx.guild.id)
        state.volume = nivel / 100
        set_guild_volume(ctx.guild.id, state.volume)
        if state.voice_client and state.voice_client.source:
            state.voice_client.source.volume = state.volume
        await ctx.respond(f"🔊 Volumen ajustado a {nivel}% (se va a recordar para la próxima).")

    @commands.slash_command(name="loop", description="Repite la canción actual o toda la cola")
    async def loop_cmd(
        self,
        ctx: discord.ApplicationContext,
        modo: Option(str, "Modo de repetición", choices=["off", "song", "queue"]),
    ):
        state = self.get_state(ctx.guild.id)
        state.loop_mode = modo
        labels = {
            "off": "🔁 Repetición desactivada.",
            "song": "🔂 Repitiendo la canción actual.",
            "queue": "🔁 Repitiendo toda la cola.",
        }
        await ctx.respond(labels[modo])

    @commands.slash_command(name="shuffle", description="Mezcla el orden de la cola")
    async def shuffle(self, ctx: discord.ApplicationContext):
        state = self.get_state(ctx.guild.id)
        if len(state.queue) < 2:
            await ctx.respond("No hay suficientes canciones en la cola para mezclar.")
            return
        items = list(state.queue)
        random.shuffle(items)
        state.queue = deque(items)
        await ctx.respond(f"🔀 Mezclé {len(items)} canciones en la cola.")

    @commands.slash_command(name="remove", description="Quita una canción de la cola por posición")
    async def remove(
        self,
        ctx: discord.ApplicationContext,
        posicion: Option(int, "Posición en la cola (1 = la próxima)"),
    ):
        state = self.get_state(ctx.guild.id)
        if posicion < 1 or posicion > len(state.queue):
            await ctx.respond(f"Posición inválida. La cola tiene {len(state.queue)} canciones.")
            return
        items = list(state.queue)
        removed = items.pop(posicion - 1)
        state.queue = deque(items)
        await ctx.respond(f"🗑️ Quité de la cola: **{removed.title}**")

    @commands.slash_command(name="history", description="Muestra lo que sonó en esta sesión para volver a ponerlo")
    async def history(self, ctx: discord.ApplicationContext):
        state = self.get_state(ctx.guild.id)
        if not state.history:
            await ctx.respond("Todavía no sonó nada en esta sesión.")
            return
        view = HistoryView(self, ctx.guild.id, ctx.author.id, state.history)
        await ctx.respond(
            f"🕘 Últimas {len(view.entries)} canciones de esta sesión, elegí una:", view=view
        )

    @commands.Cog.listener()
    async def on_voice_state_update(
        self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState
    ):
        if AUTO_DISCONNECT_SECONDS <= 0:
            return

        for state in self.states.values():
            vc = state.voice_client
            if not vc or not vc.is_connected():
                continue
            channel = vc.channel
            if before.channel != channel and after.channel != channel:
                continue

            humans = [m for m in channel.members if not m.bot]
            if not humans:
                if state.empty_since is None:
                    state.empty_since = time.monotonic()
                    self.bot.loop.create_task(self._auto_disconnect_check(state))
            else:
                state.empty_since = None

    async def _auto_disconnect_check(self, state: GuildMusicState):
        await asyncio.sleep(AUTO_DISCONNECT_SECONDS)
        if state.empty_since is None or not state.voice_client or not state.voice_client.is_connected():
            return
        channel = state.voice_client.channel
        humans = [m for m in channel.members if not m.bot]
        if humans:
            state.empty_since = None
            return

        state.queue.clear()
        state.active_playlist = None
        state.suppress_requeue = True
        state.history = []
        await state.voice_client.disconnect()
        state.voice_client = None
        state.empty_since = None
        if state.text_channel:
            await state.text_channel.send("👋 Me fui porque quedé solo en el canal de voz.")


def setup(bot: commands.Bot):
    bot.add_cog(Music(bot))