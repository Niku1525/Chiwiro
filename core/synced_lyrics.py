import difflib
import logging
import re
import unicodedata

import requests

log = logging.getLogger(__name__)

API = "https://lrclib.net/api/search"
USER_AGENT = "ChiwiroMusicBot/1.0 (bot de Discord de uso personal)"

_LRC_LINE = re.compile(r"\[(\d{1,3}):(\d{2})(?:[.:](\d{1,3}))?\]\s*(.*)")

DURATION_TOLERANCE = 12


def _parse_lrc(text: str) -> list[tuple[float, str]]:
    verses = []
    for line in text.split("\n"):
        found = _LRC_LINE.match(line.strip())
        if not found:
            continue
        minutes, seconds, fraction, words = found.groups()
        at = int(minutes) * 60 + int(seconds)
        if fraction:
            at += float(f"0.{fraction}")
        verses.append((at, words.strip()))
    verses.sort(key=lambda v: v[0])
    return verses


_FEAT = re.compile(r"\s*[\(\[]?\s*(?:feat\.?|ft\.?|featuring)\s[^)\]]*[\)\]]?", re.IGNORECASE)
_PARENS = re.compile(r"[\(（]([^)）]+)[\)）]")


def _normalize(text: str) -> str:
    clean = unicodedata.normalize("NFKD", (text or "").lower())
    clean = "".join(c for c in clean if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^\w\s]", " ", clean).split())


def _similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, _normalize(a), _normalize(b)).ratio()


def artist_variants(artist) -> list[str]:
    if not artist:
        return []

    variants: list[str] = []

    def add(value: str):
        value = (value or "").strip(" -–—·,")
        if value and value not in variants:
            variants.append(value)

    base = _FEAT.sub("", artist).strip()
    add(base)
    for inside in _PARENS.findall(base):
        add(inside)
    add(_PARENS.sub("", base))
    return variants


def _acceptable(candidate: dict, artist, duration) -> bool:
    if duration and candidate.get("duration"):
        if abs(float(candidate["duration"]) - float(duration)) <= DURATION_TOLERANCE:
            return True

    artist_name = candidate.get("artistName") or ""
    return any(_similarity(v, artist_name) >= 0.55 for v in artist_variants(artist))


def _score(candidate: dict, duration) -> float:
    points = 0.0
    if candidate.get("syncedLyrics"):
        points += 10
    if duration and candidate.get("duration"):
        diff = abs(float(candidate["duration"]) - float(duration))
        if diff <= DURATION_TOLERANCE:
            points += 5 - (diff / DURATION_TOLERANCE)
        else:
            points -= diff / 60
    if candidate.get("instrumental"):
        points -= 8
    return points


def find(title: str, artist=None, duration=None) -> dict | None:
    variants = artist_variants(artist)

    queries = []
    for variant in variants:
        queries.append({"artist_name": variant, "track_name": title})
    for variant in variants:
        queries.append({"q": f"{variant} {title}"})
    queries.append({"q": title})

    seen = []
    for query in queries:
        if query not in seen:
            seen.append(query)
    queries = seen

    for query_params in queries:
        try:
            response = requests.get(API, params=query_params, timeout=10,
                                    headers={"User-Agent": USER_AGENT})
            response.raise_for_status()
            results = response.json()
        except Exception:
            log.exception(f"[karaoke] Falló la búsqueda en lrclib: {query_params}")
            continue

        synced = [r for r in results
                  if r.get("syncedLyrics") and _acceptable(r, artist, duration)]
        if not synced:
            continue

        best = max(synced, key=lambda r: _score(r, duration))
        verses = _parse_lrc(best["syncedLyrics"])
        if not verses:
            continue

        log.info(f"[karaoke] {best.get('artistName')} - {best.get('trackName')} "
                 f"({len(verses)} versos)")
        return {
            "verses": verses,
            "title": best.get("trackName") or title,
            "artist": best.get("artistName") or (artist or ""),
            "duration": best.get("duration"),
        }

    return None


def current_index(verses: list[tuple[float, str]], at_second: float) -> int:
    index = -1
    for i, (at, _) in enumerate(verses):
        if at <= at_second:
            index = i
        else:
            break
    return index


def window(verses: list[tuple[float, str]], current: int,
           before: int = 3, after: int = 4) -> str:
    if not verses:
        return ""

    start = max(0, current - before)
    end = min(len(verses), max(current, 0) + after + 1)

    lines = []
    for i in range(start, end):
        text = verses[i][1] or "♪"
        if i == current:
            lines.append(f"**➤  {text}**")
        else:
            lines.append(f"　{text}")
    return "\n".join(lines)
