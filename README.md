# Anki Vocabulary Deck Skill

A reusable Codex skill for creating import-ready Anki `.apkg` vocabulary decks with a calm, minimal design.

## What it creates

- Front: term, clickable American-English pronunciation, and IPA
- Back: Chinese meaning, concise study note, English-labeled image, and source attribution
- Offline audio embedded in every card
- Images embedded rather than hotlinked
- Light- and dark-mode support

## Default visual style

- Black, white, and gray only
- One consistent 20px text size
- No accent colors, gradients, decorative panels, or shadows
- Images limited to 400 × 300px
- Aspect ratio preserved without cropping or stretching
- White image background for diagrams with transparent backgrounds

## Install

```bash
git clone https://github.com/qiq2026qiq/anki-vocab-deck.git ~/.codex/skills/anki-vocab-deck
```

Restart Codex if the skill does not appear immediately.

## Use

Invoke the skill directly:

```text
Use $anki-vocab-deck to turn this vocabulary list into an Anki deck.
```

The skill also activates when you ask Codex to turn a lesson vocabulary list or terminology table into Anki cards in your preferred style.

## Local builder

The included builder accepts a JSON specification:

```bash
python3 scripts/build_deck.py spec.json --output deck.apkg
```

Required Python package: `genanki`. On macOS, pronunciation audio is generated locally with `say` and converted to WAV with `afconvert`.

See [SKILL.md](./SKILL.md) for the full workflow and JSON field contract.
