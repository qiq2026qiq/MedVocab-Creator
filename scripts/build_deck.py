#!/usr/bin/env python3
"""Build a minimal grayscale Anki vocabulary deck with images and audio."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import tempfile
import wave
import zipfile

import genanki


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
.image img { display: block; max-width: 440px; max-height: 320px; width: auto; height: auto; margin: 0 auto; background: transparent; object-fit: contain; }
.source { max-width: 720px; margin: 10px auto 0; line-height: 1.45; color: #777777; }
.source a { color: inherit; text-decoration: underline; }
.nightMode.card, .nightMode .card { color: #eeeeee !important; background: #1f1f1f !important; }
.nightMode .word, .nightMode .meaning, .nightMode .note, .nightMode .note b { color: inherit !important; }
.nightMode .ipa, .nightMode .source { color: #bdbdbd !important; }
.nightMode hr#answer { border-top-color: #555555 !important; }
.nightMode .source a { color: inherit !important; }
.nightMode .image, .nightMode .image img { background: transparent !important; }
"""


def stable_id(namespace: str, value: str) -> int:
    raw = hashlib.sha256(f"{namespace}:{value}".encode("utf-8")).digest()
    return 1_000_000_000 + int.from_bytes(raw[:4], "big") % 1_000_000_000


def require_card(card: dict, index: int) -> None:
    required = ("word", "ipa", "meaning", "note_html", "image", "source_name", "source_url")
    missing = [key for key in required if not str(card.get(key, "")).strip()]
    if missing:
        raise ValueError(f"card {index} is missing: {', '.join(missing)}")


def run_tts(text: str, out_wav: Path, voice: str, rate: int, scratch: Path) -> None:
    say = shutil.which("say")
    afconvert = shutil.which("afconvert")
    if not say or not afconvert:
        raise RuntimeError("Local macOS TTS tools 'say' and 'afconvert' are required when audio_path is absent")
    aiff = scratch / f"{out_wav.stem}.aiff"
    subprocess.run([say, "-v", voice, "-r", str(rate), "-o", str(aiff), text], check=True)
    subprocess.run([afconvert, "-f", "WAVE", "-d", "LEI16@22050", str(aiff), str(out_wav)], check=True)


def validate_wav(path: Path) -> None:
    with wave.open(str(path), "rb") as audio:
        if audio.getnframes() <= 0:
            raise ValueError(f"empty audio: {path}")


def build(spec_path: Path, output_path: Path) -> None:
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    title = str(spec.get("deck_title", "")).strip()
    cards = spec.get("cards")
    if not title or not isinstance(cards, list) or not cards:
        raise ValueError("spec requires non-empty deck_title and cards")

    voice = str(spec.get("voice", "Samantha"))
    rate = int(spec.get("speech_rate", 145))
    output_path.parent.mkdir(parents=True, exist_ok=True)

    model = genanki.Model(
        stable_id("anki-vocab-model", "minimal-audio-image-v2-grouped-lines"),
        "Minimal Vocabulary with Audio and Image v2",
        fields=[
            {"name": "Word"}, {"name": "IPA"}, {"name": "Audio"},
            {"name": "Meaning"}, {"name": "Note"}, {"name": "Image"},
            {"name": "Source"},
        ],
        templates=[{
            "name": "Term to meaning",
            "qfmt": '<div class="front-line"><div class="word">{{Word}}</div><div class="audio">{{Audio}}</div></div><div class="ipa">{{IPA}}</div>',
            "afmt": '{{FrontSide}}<hr id="answer"><div class="meaning">{{Meaning}}</div><div class="note">{{Note}}</div><div class="image">{{Image}}</div><div class="source">{{Source}}</div>',
        }],
        css=CSS,
    )
    deck = genanki.Deck(stable_id("anki-vocab-deck", title), title)

    with tempfile.TemporaryDirectory(prefix="anki-vocab-") as tmp:
        tmp_path = Path(tmp)
        media_files: list[str] = []

        for index, card in enumerate(cards, 1):
            require_card(card, index)
            image_path = Path(card["image"]).expanduser().resolve()
            if not image_path.is_file():
                raise FileNotFoundError(image_path)
            image_name = f"img_{index:03d}{image_path.suffix.lower()}"
            packed_image = tmp_path / image_name
            shutil.copy2(image_path, packed_image)
            media_files.append(str(packed_image))

            audio_name = f"audio_{index:03d}.wav"
            packed_audio = tmp_path / audio_name
            if card.get("audio_path"):
                supplied = Path(card["audio_path"]).expanduser().resolve()
                if not supplied.is_file():
                    raise FileNotFoundError(supplied)
                if supplied.suffix.lower() != ".wav":
                    raise ValueError("audio_path must be WAV; omit it to use local TTS")
                shutil.copy2(supplied, packed_audio)
            else:
                run_tts(str(card.get("audio_text") or card["word"]), packed_audio, voice, rate, tmp_path)
            validate_wav(packed_audio)
            media_files.append(str(packed_audio))

            source = (
                f'图片来源：<a href="{html.escape(str(card["source_url"]))}">'
                f'{html.escape(str(card["source_name"]))}</a>'
            )
            deck.add_note(genanki.Note(
                model=model,
                fields=[
                    html.escape(str(card["word"])),
                    html.escape(str(card["ipa"])),
                    f"[sound:{audio_name}]",
                    html.escape(str(card["meaning"])),
                    str(card["note_html"]),
                    f'<img src="{image_name}">',
                    source,
                ],
                guid=genanki.guid_for(title, str(card["word"])),
                tags=["vocabulary"],
            ))

        package = genanki.Package(deck)
        package.media_files = media_files
        package.write_to_file(output_path)

    validate_package(output_path, len(cards))


def validate_package(path: Path, expected: int) -> None:
    with zipfile.ZipFile(path) as archive, tempfile.TemporaryDirectory(prefix="anki-check-") as tmp:
        media = json.loads(archive.read("media"))
        collection = next(
            name for name in archive.namelist() if name in ("collection.anki2", "collection.anki21")
        )
        archive.extract(collection, tmp)
        db = sqlite3.connect(Path(tmp) / collection)
        fields = [row[0] for row in db.execute("select flds from notes")]
        cards = db.execute("select count(*) from cards").fetchone()[0]
        audio_refs = [ref for field in fields for ref in re.findall(r"\[sound:([^\]]+)\]", field)]
        image_refs = [ref for field in fields for ref in re.findall(r'<img src="([^"]+)">', field)]
        embedded = set(media.values())
        if len(fields) != expected or cards != expected:
            raise ValueError(f"expected {expected} notes/cards, found {len(fields)}/{cards}")
        if len(audio_refs) != expected or len(image_refs) != expected:
            raise ValueError("each note must contain exactly one audio and one image reference")
        missing = (set(audio_refs) | set(image_refs)) - embedded
        if missing:
            raise ValueError(f"missing embedded media: {sorted(missing)}")
    print(json.dumps({
        "output": str(path.resolve()), "notes": expected, "cards": expected,
        "audio": expected, "images": expected, "embedded_media": expected * 2,
    }, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("spec", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    build(args.spec.resolve(), args.output.resolve())


if __name__ == "__main__":
    main()
