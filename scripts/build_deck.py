#!/usr/bin/env python3
"""Build and validate MedTerm to Anki decks with permanent media caches."""

from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
import hashlib
import html
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import tempfile
import time
import unicodedata
from urllib.parse import urlparse
import wave
import zipfile

import genanki


PROJECT_SLUG = "medterm-to-anki"
DEFAULT_CACHE_DIR = Path("~/.cache/medterm-to-anki").expanduser()
DEFAULT_VOICE = "Samantha"
DEFAULT_RATE = 145
DEFAULT_AUDIO_WORKERS = 8
AUDIO_FORMAT = "WAVE"
AUDIO_ENCODING = "LEI16"
AUDIO_SAMPLE_RATE = 22_050
AUDIO_CHANNELS = 1
AUDIO_CACHE_SCHEMA = 1
IMAGE_CACHE_SCHEMA = 1
NEGATIVE_IMAGE_CACHE_SCHEMA = 1
NEGATIVE_IMAGE_CACHE_DAYS = 90
NO_IMAGE_REASON = "confirmed_no_suitable_cleveland_image"

# These legacy namespaces intentionally preserve model/deck IDs created by the
# predecessor skill. Changing them would create duplicate note types on import.
MODEL_ID_NAMESPACE = "anki-vocab-model"
DECK_ID_NAMESPACE = "anki-vocab-deck"

CSS = r"""
.card {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Noto Sans CJK SC", Arial, sans-serif;
  font-size: 20px;
  text-align: center;
  color: #1f1f1f;
  background: #ffffff;
  padding: 24px;
}
.word, .ipa, .meaning, .note, .source { font-size: inherit; }
.word, .ipa, .meaning { white-space: pre-line; }
.word, .meaning { font-weight: 600; }
.word { line-height: 1.5; }
.front-line { display: flex; align-items: center; justify-content: center; gap: 12px; flex-wrap: wrap; }
.audio { display: inline-flex; align-items: center; min-width: 28px; }
.audio .replay-button svg { width: 32px; height: 32px; }
.ipa, .meaning { line-height: 1.6; }
.ipa { margin-top: 10px; color: #666666; }
hr#answer { border: 0; border-top: 1px solid #cccccc; margin: 26px 0 22px; }
.note { max-width: 720px; margin: 16px auto 20px; padding: 0; line-height: 1.7; text-align: left; }
.image { box-sizing: border-box; margin: 16px auto; padding: 0; background: transparent; }
.image img { display: block; width: auto; height: auto; margin: 0 auto; background: transparent; object-fit: contain; }
.image img.media-landscape:not([width]):not([height]):not([style]) { max-width: 480px; max-height: 280px; }
.image img.media-portrait:not([width]):not([height]):not([style]) { max-width: 330px; max-height: 390px; }
.image img.media-square:not([width]):not([height]):not([style]) { max-width: 350px; max-height: 350px; }
.source { max-width: 720px; margin: 10px auto 0; line-height: 1.45; color: #777777; }
.source a { color: inherit; text-decoration: underline; }
.nightMode.card, .nightMode .card { color: #eeeeee !important; background: #1f1f1f !important; }
.nightMode .word, .nightMode .meaning, .nightMode .note, .nightMode .note b { color: inherit !important; }
.nightMode .ipa, .nightMode .source { color: #bdbdbd !important; }
.nightMode hr#answer { border-top-color: #555555 !important; }
.nightMode .source a { color: inherit !important; }
.nightMode .image, .nightMode .image img { background: transparent !important; }
"""

QFMT = (
    '<div class="front-line"><div class="word">{{Word}}</div>'
    '<div class="audio">{{Audio}}</div></div><div class="ipa">{{IPA}}</div>'
)

AFMT = r"""{{FrontSide}}<hr id="answer"><div class="meaning">{{Meaning}}</div><div class="note">{{Note}}</div><div class="image">{{Image}}</div><div class="source">{{Source}}</div>
<script>
(function () {
  var image = document.querySelector('.image img');
  if (!image) return;
  function classify() {
    var ratio = image.naturalWidth / image.naturalHeight;
    image.classList.remove('media-landscape', 'media-portrait', 'media-square');
    image.classList.add(ratio > 1.08 ? 'media-landscape' : ratio < 0.92 ? 'media-portrait' : 'media-square');
  }
  if (image.complete && image.naturalHeight) classify();
  else image.addEventListener('load', classify, {once: true});
}());
</script>"""


class ImageCacheMissError(RuntimeError):
    def __init__(self, misses: list[dict]):
        super().__init__("image-cache misses require an approved Cleveland Clinic image or no_image: true")
        self.misses = misses


def stable_id(namespace: str, value: str) -> int:
    raw = hashlib.sha256(f"{namespace}:{value}".encode("utf-8")).digest()
    return 1_000_000_000 + int.from_bytes(raw[:4], "big") % 1_000_000_000


def normalize_text(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value)).strip().casefold()
    return " ".join(text.split())


def normalize_audio_text(value: object) -> str:
    # Preserve case and punctuation because macOS voices may pronounce them
    # differently (for example, "US" versus "us").
    text = unicodedata.normalize("NFKC", str(value)).strip()
    return " ".join(text.split())


def normalize_multiline(value: object) -> str:
    lines = [normalize_text(line) for line in str(value).splitlines()]
    return "\n".join(line for line in lines if line)


def is_cleveland_clinic_url(value: object) -> bool:
    hostname = (urlparse(str(value).strip()).hostname or "").lower().rstrip(".")
    return hostname == "clevelandclinic.org" or hostname.endswith(".clevelandclinic.org")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def json_hash(payload: dict) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def cache_layout(cache_dir: Path, create: bool = False) -> dict[str, Path]:
    root = cache_dir.expanduser().resolve()
    layout = {
        "root": root,
        "audio": root / "audio",
        "images": root / "images",
        "audio_metadata": root / "metadata" / "audio",
        "image_metadata": root / "metadata" / "images",
        "negative_image_metadata": root / "metadata" / "no-images",
    }
    if create:
        for key, path in layout.items():
            if key != "root":
                path.mkdir(parents=True, exist_ok=True)
    return layout


def resolve_source_path(value: object, spec_dir: Path) -> Path:
    path = Path(str(value)).expanduser()
    if path.is_absolute():
        return path.resolve()
    beside_spec = (spec_dir / path).resolve()
    return beside_spec if beside_spec.exists() else path.resolve()


def copy_atomic(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=destination.parent, prefix=f".{destination.stem}-", suffix=destination.suffix, delete=False
    ) as handle:
        staging = Path(handle.name)
    try:
        shutil.copy2(source, staging)
        os.replace(staging, destination)
    finally:
        staging.unlink(missing_ok=True)


def write_json_atomic(destination: Path, payload: dict) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=destination.parent,
        prefix=f".{destination.stem}-", suffix=".json", delete=False,
    ) as handle:
        staging = Path(handle.name)
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    try:
        os.replace(staging, destination)
    finally:
        staging.unlink(missing_ok=True)


def require_card_content(card: dict, index: int) -> None:
    word = str(card.get("word", "")).strip()
    missing = [key for key in ("word", "ipa", "meaning") if not str(card.get(key, "")).strip()]
    if not str(card.get("note", "")).strip() and not str(card.get("note_html", "")).strip():
        missing.append("note or note_html")
    if missing:
        raise ValueError(f"card {index} is missing: {', '.join(missing)}")
    if "\n" in word or "\r" in word:
        raise ValueError(f"card {index} must contain exactly one input entry in 'word'; split separate entries into separate cards")
    if "no_image" in card and not isinstance(card["no_image"], bool):
        raise ValueError(f"card {index} no_image must be true or false")
    if card.get("no_image") and card.get("image"):
        raise ValueError(f"card {index} cannot contain both image and no_image: true")
    if card.get("no_image"):
        if card.get("no_image_reason") != NO_IMAGE_REASON:
            raise ValueError(
                f"card {index} no_image requires no_image_reason={NO_IMAGE_REASON!r}"
            )
        checked_at = str(card.get("image_search_checked_at", "")).strip()
        try:
            checked = datetime.fromisoformat(checked_at.replace("Z", "+00:00"))
        except ValueError:
            raise ValueError(
                f"card {index} no_image requires an ISO-8601 image_search_checked_at"
            ) from None
        if checked.tzinfo is None:
            raise ValueError(f"card {index} image_search_checked_at must include a timezone")
    if not card.get("image") and (card.get("source_name") or card.get("source_url")):
        raise ValueError(f"card {index} cannot contain image source fields without image")


def image_identity(card: dict) -> dict[str, str]:
    raw_identity = str(card.get("semantic_identity") or card["word"]).strip()
    raw_query = str(card.get("image_query") or raw_identity).strip()
    normalized_identity = normalize_multiline(raw_identity)
    normalized_query = normalize_text(raw_query)
    payload = {
        "schema": IMAGE_CACHE_SCHEMA,
        "semantic_identity": normalized_identity,
        "image_query": normalized_query,
    }
    return {
        "key": json_hash(payload),
        "raw_identity": raw_identity,
        "raw_query": raw_query,
        "normalized_identity": normalized_identity,
        "normalized_query": normalized_query,
    }


def no_image_confirmation_is_current(card: dict) -> bool:
    if not card.get("no_image"):
        return False
    checked_at = datetime.fromisoformat(
        str(card["image_search_checked_at"]).strip().replace("Z", "+00:00")
    ).astimezone(timezone.utc)
    return checked_at + timedelta(days=NEGATIVE_IMAGE_CACHE_DAYS) > datetime.now(timezone.utc)


def get_cached_image(card: dict, layout: dict[str, Path]) -> dict | None:
    identity = image_identity(card)
    metadata_path = layout["image_metadata"] / f"{identity['key']}.json"
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        filename = metadata["cached_image_filename"]
        cached_path = layout["images"] / filename
        valid = (
            metadata.get("schema") == IMAGE_CACHE_SCHEMA
            and metadata.get("cache_key") == identity["key"]
            and metadata.get("normalized_semantic_identity") == identity["normalized_identity"]
            and metadata.get("normalized_image_query") == identity["normalized_query"]
            and Path(filename).name == filename
            and cached_path.is_file()
            and cached_path.stat().st_size > 0
            and sha256_file(cached_path) == metadata.get("image_sha256")
            and str(metadata.get("source_name", "")).strip()
            and is_cleveland_clinic_url(metadata.get("source_url", ""))
        )
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return None
    if not valid:
        return None
    return {
        "path": cached_path,
        "source_name": str(metadata["source_name"]),
        "source_url": str(metadata["source_url"]),
        "cache_key": identity["key"],
    }


def get_cached_no_image(card: dict, layout: dict[str, Path]) -> dict | None:
    identity = image_identity(card)
    metadata_path = layout["negative_image_metadata"] / f"{identity['key']}.json"
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        expires_at = datetime.fromisoformat(str(metadata["expires_at"]).replace("Z", "+00:00"))
        valid = (
            metadata.get("schema") == NEGATIVE_IMAGE_CACHE_SCHEMA
            and metadata.get("cache_key") == identity["key"]
            and metadata.get("normalized_semantic_identity") == identity["normalized_identity"]
            and metadata.get("normalized_image_query") == identity["normalized_query"]
            and metadata.get("reason") == NO_IMAGE_REASON
            and expires_at.tzinfo is not None
            and expires_at > datetime.now(timezone.utc)
        )
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return None
    if not valid:
        return None
    return {
        "cache_key": identity["key"],
        "checked_at": str(metadata["checked_at"]),
        "expires_at": str(metadata["expires_at"]),
    }


def cache_confirmed_no_image(card: dict, layout: dict[str, Path]) -> dict:
    identity = image_identity(card)
    checked_at = datetime.fromisoformat(
        str(card["image_search_checked_at"]).strip().replace("Z", "+00:00")
    ).astimezone(timezone.utc)
    expires_at = checked_at + timedelta(days=NEGATIVE_IMAGE_CACHE_DAYS)
    metadata = {
        "schema": NEGATIVE_IMAGE_CACHE_SCHEMA,
        "cache_key": identity["key"],
        "card_term_group": str(card["word"]),
        "semantic_identity": identity["raw_identity"],
        "normalized_semantic_identity": identity["normalized_identity"],
        "image_query": identity["raw_query"],
        "normalized_image_query": identity["normalized_query"],
        "reason": NO_IMAGE_REASON,
        "checked_at": checked_at.isoformat(),
        "expires_at": expires_at.isoformat(),
    }
    write_json_atomic(layout["negative_image_metadata"] / f"{identity['key']}.json", metadata)
    return metadata


def cache_selected_image(card: dict, source: Path, layout: dict[str, Path]) -> dict:
    if not source.is_file() or source.stat().st_size <= 0:
        raise FileNotFoundError(source)
    if not source.suffix:
        raise ValueError(f"image file needs an extension: {source}")
    identity = image_identity(card)
    source_name = str(card.get("source_name", "")).strip()
    source_url = str(card.get("source_url", "")).strip()
    if not source_name or not source_url:
        raise ValueError(f"image cache miss for {card['word']!r} requires source_name and source_url")
    if not is_cleveland_clinic_url(source_url):
        raise ValueError(f"image source for {card['word']!r} must be clevelandclinic.org")
    cached_path = layout["images"] / f"{identity['key']}{source.suffix.lower()}"
    image_sha256 = sha256_file(source)
    if not cached_path.is_file() or sha256_file(cached_path) != image_sha256:
        copy_atomic(source, cached_path)
    metadata = {
        "schema": IMAGE_CACHE_SCHEMA,
        "cache_key": identity["key"],
        "card_term_group": str(card["word"]),
        "semantic_identity": identity["raw_identity"],
        "normalized_semantic_identity": identity["normalized_identity"],
        "image_query": identity["raw_query"],
        "normalized_image_query": identity["normalized_query"],
        "cached_image_filename": cached_path.name,
        "cached_image_path": str(cached_path),
        "image_sha256": image_sha256,
        "source_name": source_name,
        "source_url": source_url,
    }
    write_json_atomic(layout["image_metadata"] / f"{identity['key']}.json", metadata)
    return {
        "path": cached_path,
        "source_name": source_name,
        "source_url": source_url,
        "cache_key": identity["key"],
    }


def inspect_image_cache(spec: dict, layout: dict[str, Path]) -> dict:
    cards = spec["cards"]
    items = []
    hits = 0
    no_image = 0
    negative_hits = 0
    for index, card in enumerate(cards, 1):
        require_card_content(card, index)
        identity = image_identity(card)
        cached = None if card.get("refresh_image_cache") else get_cached_image(card, layout)
        negative = None if card.get("refresh_image_cache") else get_cached_no_image(card, layout)
        fresh_no_image = no_image_confirmation_is_current(card)
        status = "hit" if cached else "negative-hit" if negative else "confirmed-no-image" if fresh_no_image else "miss"
        hits += int(bool(cached))
        negative_hits += int(not cached and bool(negative))
        no_image += int(not cached and not negative and fresh_no_image)
        items.append({
            "index": index,
            "word": str(card["word"]),
            "semantic_identity": identity["raw_identity"],
            "image_query": identity["raw_query"],
            "status": status,
            "approved_image_supplied": bool(card.get("image")),
            "negative_cache_expires_at": negative["expires_at"] if negative else "",
        })
    return {
        "cache_dir": str(layout["root"]),
        "hits": hits,
        "misses": len(cards) - hits - negative_hits - no_image,
        "no_image": no_image,
        "negative_hits": negative_hits,
        "cards": items,
    }


def resolve_images(cards: list[dict], spec_dir: Path, layout: dict[str, Path]) -> tuple[list[dict | None], dict]:
    resources: list[dict | None] = []
    misses: list[dict] = []
    stats = {"hits": 0, "negative_hits": 0, "misses": 0, "stored": 0, "without_image": 0}
    for index, card in enumerate(cards, 1):
        cached = None if card.get("refresh_image_cache") else get_cached_image(card, layout)
        if cached:
            stats["hits"] += 1
            resources.append(cached)
            continue
        negative = None if card.get("refresh_image_cache") else get_cached_no_image(card, layout)
        if negative:
            stats["negative_hits"] += 1
            stats["without_image"] += 1
            resources.append(None)
            continue
        identity = image_identity(card)
        if no_image_confirmation_is_current(card):
            cache_confirmed_no_image(card, layout)
            stats["without_image"] += 1
            resources.append(None)
            continue
        if not card.get("image"):
            stats["misses"] += 1
            misses.append({
                "index": index,
                "word": str(card["word"]),
                "semantic_identity": identity["raw_identity"],
                "image_query": identity["raw_query"],
            })
            resources.append(None)
            continue
        source = resolve_source_path(card["image"], spec_dir)
        resources.append(cache_selected_image(card, source, layout))
        stats["stored"] += 1
    if misses:
        raise ImageCacheMissError(misses)

    seen: dict[str, int] = {}
    for index, resource in enumerate(resources, 1):
        if resource is None:
            continue
        digest = sha256_file(resource["path"])
        if digest in seen:
            raise ValueError(f"cards {seen[digest]} and {index} use duplicate image content")
        seen[digest] = index
    return resources, stats


def audio_parameters(text: str, voice: str, rate: int) -> dict:
    return {
        "schema": AUDIO_CACHE_SCHEMA,
        "normalized_audio_text": normalize_audio_text(text),
        "voice": voice,
        "speech_rate": rate,
        "format": AUDIO_FORMAT,
        "encoding": AUDIO_ENCODING,
        "sample_rate": AUDIO_SAMPLE_RATE,
        "channels": AUDIO_CHANNELS,
    }


def audio_cache_key(text: str, voice: str, rate: int) -> str:
    return json_hash(audio_parameters(text, voice, rate))


def validate_wav(
    path: Path, expected_rate: int | None = None, expected_channels: int | None = None
) -> None:
    with wave.open(str(path), "rb") as audio:
        if audio.getnframes() <= 0:
            raise ValueError(f"empty audio: {path}")
        if expected_rate is not None and audio.getframerate() != expected_rate:
            raise ValueError(f"unexpected sample rate in {path}: {audio.getframerate()}")
        if expected_channels is not None and audio.getnchannels() != expected_channels:
            raise ValueError(f"unexpected channel count in {path}: {audio.getnchannels()}")


def cached_audio_is_valid(path: Path) -> bool:
    try:
        validate_wav(path, AUDIO_SAMPLE_RATE, AUDIO_CHANNELS)
        return True
    except (OSError, EOFError, ValueError, wave.Error):
        return False


def run_checked(command: list[str]) -> None:
    result = subprocess.run(command, check=False, capture_output=True, text=True)
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
        raise RuntimeError(f"command failed: {command[0]}: {detail}")


def generate_audio(text: str, destination: Path, voice: str, rate: int, key: str) -> None:
    say = shutil.which("say")
    afconvert = shutil.which("afconvert")
    if not say or not afconvert:
        raise RuntimeError("macOS tools 'say' and 'afconvert' are required when audio_path is absent")
    with tempfile.TemporaryDirectory(prefix=f"medterm-audio-{key[:10]}-") as scratch:
        scratch_path = Path(scratch)
        aiff = scratch_path / "speech.aiff"
        wav_path = scratch_path / "speech.wav"
        run_checked([say, "-v", voice, "-r", str(rate), "-o", str(aiff), text])
        run_checked([
            afconvert, "-f", AUDIO_FORMAT, "-d", f"{AUDIO_ENCODING}@{AUDIO_SAMPLE_RATE}",
            "-c", str(AUDIO_CHANNELS), str(aiff), str(wav_path),
        ])
        validate_wav(wav_path, AUDIO_SAMPLE_RATE, AUDIO_CHANNELS)
        copy_atomic(wav_path, destination)


def prepare_audio(
    cards: list[dict], spec_dir: Path, layout: dict[str, Path], voice: str, rate: int, workers: int
) -> tuple[list[Path], dict]:
    if workers < 1 or workers > 16:
        raise ValueError("audio_workers must be between 1 and 16")
    paths: list[Path | None] = [None] * len(cards)
    jobs: dict[str, dict] = {}
    stats = {"hits": 0, "misses": 0, "generated": 0, "supplied": 0, "tts_seconds": 0.0}

    for index, card in enumerate(cards):
        if card.get("audio_path"):
            supplied = resolve_source_path(card["audio_path"], spec_dir)
            if not supplied.is_file():
                raise FileNotFoundError(supplied)
            if supplied.suffix.lower() != ".wav":
                raise ValueError("audio_path must be WAV; omit it to use local TTS")
            validate_wav(supplied)
            paths[index] = supplied
            stats["supplied"] += 1
            continue

        text = str(card.get("audio_text") or card["word"]).strip()
        key = audio_cache_key(text, voice, rate)
        destination = layout["audio"] / f"{key}.wav"
        if cached_audio_is_valid(destination):
            paths[index] = destination
            stats["hits"] += 1
            continue
        stats["misses"] += 1
        jobs.setdefault(key, {"text": text, "path": destination, "indices": []})["indices"].append(index)

    started = time.perf_counter()
    if jobs:
        with ThreadPoolExecutor(max_workers=min(workers, len(jobs)), thread_name_prefix="medterm-tts") as pool:
            futures = {
                pool.submit(generate_audio, job["text"], job["path"], voice, rate, key): key
                for key, job in jobs.items()
            }
            for future in as_completed(futures):
                key = futures[future]
                future.result()
                job = jobs[key]
                params = audio_parameters(job["text"], voice, rate)
                metadata = {**params, "cache_key": key, "cached_audio_path": str(job["path"])}
                write_json_atomic(layout["audio_metadata"] / f"{key}.json", metadata)
                for index in job["indices"]:
                    paths[index] = job["path"]
                stats["generated"] += 1
    stats["tts_seconds"] = round(time.perf_counter() - started, 4)
    return [path for path in paths if path is not None], stats


def load_spec(spec_path: Path) -> dict:
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    title = str(spec.get("deck_title", "")).strip()
    cards = spec.get("cards")
    if not title or not isinstance(cards, list) or not cards:
        raise ValueError("spec requires non-empty deck_title and cards")
    for index, card in enumerate(cards, 1):
        if not isinstance(card, dict):
            raise ValueError(f"card {index} must be an object")
        require_card_content(card, index)
    return spec


def make_model() -> genanki.Model:
    return genanki.Model(
        stable_id(MODEL_ID_NAMESPACE, "minimal-audio-image-v2-grouped-lines"),
        "Minimal Vocabulary with Audio and Image v2",
        fields=[
            {"name": "Word"}, {"name": "IPA"}, {"name": "Audio"},
            {"name": "Meaning"}, {"name": "Note"}, {"name": "Image"}, {"name": "Source"},
        ],
        templates=[{"name": "Term to meaning", "qfmt": QFMT, "afmt": AFMT}],
        css=CSS,
    )


def note_html(card: dict) -> str:
    if str(card.get("note_html", "")).strip():
        return str(card["note_html"])
    return html.escape(str(card["note"])).replace("\n", "<br>")


def validate_package(path: Path, expected: int) -> dict:
    with zipfile.ZipFile(path) as archive, tempfile.TemporaryDirectory(prefix="medterm-check-") as scratch:
        corrupt = archive.testzip()
        if corrupt:
            raise ValueError(f"corrupt zip member: {corrupt}")
        names = set(archive.namelist())
        if "media" not in names:
            raise ValueError("package has no media manifest")
        collection = next((name for name in ("collection.anki2", "collection.anki21") if name in names), None)
        if not collection:
            raise ValueError("package has no readable Anki collection")
        media = json.loads(archive.read("media"))
        archive.extract(collection, scratch)
        with sqlite3.connect(Path(scratch) / collection) as database:
            rows = [row[0] for row in database.execute("select flds from notes")]
            card_count = int(database.execute("select count(*) from cards").fetchone()[0])
        if len(rows) != expected or card_count != expected:
            raise ValueError(f"expected {expected} notes/cards, found {len(rows)}/{card_count}")
        split_fields = [row.split("\x1f") for row in rows]
        if any(len(fields) != 7 or any(not field.strip() for field in fields[:5]) for fields in split_fields):
            raise ValueError("each note must contain seven fields with Word, IPA, Audio, Meaning, and Note non-empty")
        if any(bool(fields[5].strip()) != bool(fields[6].strip()) for fields in split_fields):
            raise ValueError("Image and Source must either both be populated or both be empty")
        audio_refs = [ref for row in rows for ref in re.findall(r"\[sound:([^\]]+)\]", row)]
        image_refs = [ref for row in rows for ref in re.findall(r'<img src="([^"]+)">', row)]
        if len(audio_refs) != expected:
            raise ValueError("each note must contain exactly one audio reference")
        if len(set(audio_refs)) != expected or len(set(image_refs)) != len(image_refs):
            raise ValueError("each populated media field must use a unique filename")
        for fields in split_fields:
            if not fields[5].strip():
                continue
            match = re.search(r'href="([^"]+)"', fields[6])
            if not match or not is_cleveland_clinic_url(html.unescape(match.group(1))):
                raise ValueError("every populated image source must link to clevelandclinic.org")
        embedded = set(media.values())
        missing = (set(audio_refs) | set(image_refs)) - embedded
        if missing:
            raise ValueError(f"missing embedded media: {sorted(missing)}")
        return {
            "notes": expected,
            "cards": expected,
            "audio": len(audio_refs),
            "images": len(image_refs),
            "embedded_media": len(embedded),
        }


def prepare_media_manifest(
    spec_path: Path, manifest_path: Path, cache_dir: Path, audio_workers_override: int | None
) -> dict:
    started = time.perf_counter()
    spec = load_spec(spec_path)
    cards = spec["cards"]
    voice = str(spec.get("voice", DEFAULT_VOICE)).strip() or DEFAULT_VOICE
    rate = int(spec.get("speech_rate", DEFAULT_RATE))
    workers = int(audio_workers_override or spec.get("audio_workers", DEFAULT_AUDIO_WORKERS))
    layout = cache_layout(cache_dir, create=True)
    images, image_stats = resolve_images(cards, spec_path.parent, layout)
    audio, audio_stats = prepare_audio(cards, spec_path.parent, layout, voice, rate, workers)
    if len(audio) != len(cards):
        raise RuntimeError("internal error: not every card received audio")

    prepared_cards = []
    for card, image_resource, audio_path in zip(cards, images, audio):
        source_html = ""
        if image_resource:
            source_html = (
                f'图片来源：<a href="{html.escape(image_resource["source_url"], quote=True)}">'
                f'{html.escape(image_resource["source_name"])}</a>'
            )
        prepared_cards.append({
            "word": str(card["word"]),
            "ipa": str(card["ipa"]),
            "meaning": str(card["meaning"]),
            "note_html": note_html(card),
            "audio_path": str(audio_path),
            "image_path": str(image_resource["path"]) if image_resource else "",
            "source_name": image_resource["source_name"] if image_resource else "",
            "source_url": image_resource["source_url"] if image_resource else "",
            "source_html": source_html,
        })
    manifest = {
        "deck_title": str(spec["deck_title"]).strip(),
        "note_type": "Minimal Vocabulary with Audio and Image v2",
        "cache_dir": str(layout["root"]),
        "cards": prepared_cards,
    }
    write_json_atomic(manifest_path, manifest)
    return {
        "manifest": str(manifest_path.resolve()),
        "cache_dir": str(layout["root"]),
        "cards": len(cards),
        "total_seconds": round(time.perf_counter() - started, 4),
        "tts_seconds": audio_stats.pop("tts_seconds"),
        "audio_cache": audio_stats,
        "image_cache": image_stats,
    }


def build(
    spec_path: Path, output_path: Path, cache_dir: Path, audio_workers_override: int | None
) -> dict:
    started = time.perf_counter()
    spec = load_spec(spec_path)
    title = str(spec["deck_title"]).strip()
    cards = spec["cards"]
    voice = str(spec.get("voice", DEFAULT_VOICE)).strip() or DEFAULT_VOICE
    rate = int(spec.get("speech_rate", DEFAULT_RATE))
    workers = int(audio_workers_override or spec.get("audio_workers", DEFAULT_AUDIO_WORKERS))
    layout = cache_layout(cache_dir, create=True)

    images, image_stats = resolve_images(cards, spec_path.parent, layout)
    audio, audio_stats = prepare_audio(cards, spec_path.parent, layout, voice, rate, workers)
    if len(audio) != len(cards):
        raise RuntimeError("internal error: not every card received audio")

    model = make_model()
    deck = genanki.Deck(stable_id(DECK_ID_NAMESPACE, title), title)
    word_counts = Counter(str(card["word"]).strip() for card in cards)
    word_occurrences: Counter[str] = Counter()
    with tempfile.TemporaryDirectory(prefix="medterm-to-anki-build-") as scratch:
        scratch_path = Path(scratch)
        media_files: list[str] = []
        for index, (card, image_resource, audio_path) in enumerate(zip(cards, images, audio), 1):
            word_key = str(card["word"]).strip()
            word_occurrences[word_key] += 1
            audio_name = f"audio_{index:03d}.wav"
            packed_audio = scratch_path / audio_name
            shutil.copy2(audio_path, packed_audio)
            validate_wav(packed_audio)
            media_files.append(str(packed_audio))
            image_html = ""
            source = ""
            if image_resource:
                image_name = f"img_{index:03d}{image_resource['path'].suffix.lower()}"
                packed_image = scratch_path / image_name
                shutil.copy2(image_resource["path"], packed_image)
                media_files.append(str(packed_image))
                image_html = f'<img src="{image_name}">'
                source = (
                    f'图片来源：<a href="{html.escape(image_resource["source_url"], quote=True)}">'
                    f'{html.escape(image_resource["source_name"])}</a>'
                )
            deck.add_note(genanki.Note(
                model=model,
                fields=[
                    html.escape(str(card["word"])),
                    html.escape(str(card["ipa"])),
                    f"[sound:{audio_name}]",
                    html.escape(str(card["meaning"])),
                    note_html(card),
                    image_html,
                    source,
                ],
                guid=genanki.guid_for(
                    title,
                    word_key
                    if word_counts[word_key] == 1
                    else f"{word_key}\x00{word_occurrences[word_key]}",
                ),
                tags=["vocabulary"],
            ))

        package = genanki.Package(deck)
        package.media_files = media_files
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            dir=output_path.parent, prefix=".medterm-to-anki-", suffix=".apkg", delete=False
        ) as handle:
            staging = Path(handle.name)
        try:
            package.write_to_file(staging)
            validation = validate_package(staging, len(cards))
            os.replace(staging, output_path)
        finally:
            staging.unlink(missing_ok=True)

    return {
        "output": str(output_path.resolve()),
        "cache_dir": str(layout["root"]),
        "total_seconds": round(time.perf_counter() - started, 4),
        "tts_seconds": audio_stats.pop("tts_seconds"),
        "audio_cache": audio_stats,
        "image_cache": image_stats,
        **validation,
    }


def print_json(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("spec", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--prepare-media", type=Path, metavar="MANIFEST_JSON")
    parser.add_argument("--inspect-image-cache", action="store_true")
    parser.add_argument("--cache-dir", type=Path)
    parser.add_argument("--audio-workers", type=int)
    args = parser.parse_args()

    spec_path = args.spec.expanduser().resolve()
    cache_dir = args.cache_dir or Path(os.environ.get("MEDTERM_TO_ANKI_CACHE", DEFAULT_CACHE_DIR))
    spec = load_spec(spec_path)
    if args.inspect_image_cache:
        print_json(inspect_image_cache(spec, cache_layout(cache_dir, create=False)))
        return
    if args.output is not None and args.prepare_media is not None:
        parser.error("choose either --output or --prepare-media")
    if args.output is None and args.prepare_media is None:
        parser.error("--output or --prepare-media is required unless --inspect-image-cache is used")
    try:
        if args.prepare_media is not None:
            result = prepare_media_manifest(
                spec_path, args.prepare_media.expanduser().resolve(), cache_dir, args.audio_workers
            )
        else:
            result = build(spec_path, args.output.expanduser().resolve(), cache_dir, args.audio_workers)
    except ImageCacheMissError as error:
        print_json({
            "error": str(error),
            "cache_dir": str(cache_layout(cache_dir)["root"]),
            "image_cache_misses": error.misses,
        })
        raise SystemExit(2) from None
    print_json(result)


if __name__ == "__main__":
    main()
