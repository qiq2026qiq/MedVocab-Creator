---
name: anki-vocab-deck
description: Create or revise downloadable Anki .apkg vocabulary decks in the user's established minimal style, with IPA, offline pronunciation audio, concise Chinese explanations, and embedded attributed images. Use when the user asks to turn a word list, lesson vocabulary, or terminology table into Anki cards, or asks for “my preferred Anki style.” Do not use for ordinary Anki troubleshooting unless deck creation or styling is requested.
---

# Anki Vocabulary Deck

Create an import-ready `.apkg`, not merely a CSV, unless the user asks otherwise. Preserve every supplied term unless the user requests selection or deduplication.

## Card contract

Each note has one forward card:

- Front: term or phrase with a clickable pronunciation button beside it; IPA on the next line.
- Back: Chinese meaning, one concise study note, one relevant high-quality image with English labels when available, and image attribution/source.
- For synonym cards, keep all synonyms on one card and read them sequentially in the audio.
- Default to General American IPA and American-English audio unless the user requests another variety.

## Fixed visual style

Treat these as defaults learned from the user; do not ask the user to rediscover them:

- Use only black, white, and gray. No accent colors, gradients, decorative panels, or shadows.
- Use Anki's ordinary 20px size for every text field: term, IPA, meaning, note, and source. Hierarchy may use spacing and modest bold weight, never different font sizes.
- Support Anki light and dark themes with high-contrast grayscale text.
- Keep diagram panels white because many anatomy images have transparent backgrounds with black labels.
- Constrain every image to at most 400px wide and 300px high. Preserve aspect ratio with `object-fit: contain`; never crop, stretch, or require per-card sizing.
- Keep audio user-triggered rather than autoplaying.

## Images and audio

When web images are requested, search for English-labeled educational diagrams. Prefer Wikimedia Commons, OpenStax, NIH/NCI/NIDDK, government, university, or other sources with clear reuse terms. Embed the image rather than hotlinking it, and put a compact source link on the back. Avoid arbitrary unlicensed image-result thumbnails.

Create one offline audio file per card. On macOS, prefer the local `Samantha` voice at a measured rate and convert to mono 22,050 Hz WAV. If local TTS is unavailable, use another authorized local TTS method; do not silently omit audio.

## Build and verify

Prepare a JSON specification and run:

```bash
python3 scripts/build_deck.py spec.json --output deck.apkg
```

The JSON object requires `deck_title` and `cards`. Each card requires `word`, `ipa`, `meaning`, `note_html`, `image`, `source_name`, and `source_url`; `audio_text` and `audio_path` are optional. `image` and `audio_path` are local paths. Use `audio_text` when the written front contains slashes, abbreviations, or punctuation that TTS should not read literally.

After building, verify that note count equals card count, every note has one audio reference and one image reference, all referenced media is embedded, and the package opens as a valid zip/SQLite Anki package. Save the final `.apkg` in the user-requested location; otherwise use the current task's output directory. Copy to Downloads only when explicitly requested.
