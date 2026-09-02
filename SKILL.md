---
name: anki-vocab-forge
description: Create or revise Anki vocabulary decks in the user's established minimal style, with contrast-grouped terms, IPA, offline pronunciation audio, concise Chinese explanations, and embedded attributed images. By default, import directly through AnkiConnect; create a downloadable .apkg only when the user explicitly requests a file. Use when the user asks to turn a word list, lesson vocabulary, or terminology table into Anki cards, or asks for “my preferred Anki style.” Do not use for ordinary Anki troubleshooting unless deck creation or styling is requested.
---

# Anki Vocabulary Forge

Preserve every supplied term unless the user requests selection or deduplication. By default, import directly through AnkiConnect into the exact deck or subdeck the user names (for example, `MT::风湿免疫病`). If the user has not specified a target deck or subdeck, ask where the cards should go before importing. Only when the user explicitly asks for an `.apkg` or another file should you generate the file instead of connecting to Anki; in that case, do not perform a live AnkiConnect import unless the user asks for both.

## Card contract

Each note has one forward card:

- Front: one term or a compact contrast group with a clickable pronunciation button beside it; IPA appears below in the same order.
- Back: the corresponding Chinese meaning or meanings in the same order, one concise study note, one relevant high-quality image with English labels when available, and image attribution/source.
- For synonym cards, keep all synonyms on one card and read them sequentially in the audio.
- Default to General American IPA and American-English audio unless the user requests another variety.

## Grouping and card economy

Do not mechanically create one card for every input row. Before building, identify the smallest useful learning units and consolidate terms when comparison makes them easier to remember.

- Put two to four terms on one card when they share the same headword and form a natural contrast, differ mainly by one modifier, or are routinely learned together. Strong defaults include `closed fracture ↔ open fracture`, `stable fracture ↔ unstable fracture`, `closed reduction ↔ open reduction`, and `internal fixation ↔ external fixation`.
- Also combine true synonyms, alternate names, and acronym expansions on one card.
- Preserve every supplied term, but card count may be lower than term count because several terms can belong to one note.
- On a grouped card, put each English term on its own line. Put each IPA and Chinese meaning on its own corresponding line in exactly the same order. Use `audio_text` to read all terms sequentially with a short pause.
- Use one comparison note that states the decisive difference, and choose an image that supports the whole group rather than only one member.
- Do not group terms merely because they occur in the same chapter. Keep a term separate when it has a distinct mechanism, requires independent emergency recognition, needs a different image, or would make the card crowded. Prefer compact groups of two; use three or four only when the relationship is genuinely clearer together.

## Fixed visual style

Treat these as defaults learned from the user; do not ask the user to rediscover them:

- Use only black, white, and gray. No accent colors, gradients, decorative panels, or shadows.
- Use Anki's ordinary 20px size for every text field: term, IPA, meaning, note, and source. Hierarchy may use spacing and modest bold weight, never different font sizes.
- Support Anki light and dark themes with high-contrast grayscale text.
- Do not put a white (or any colored) backing panel, padding, or frame behind images. Keep the image container transparent in both light and dark mode; source images that genuinely contain a white background are acceptable.
- Preserve each image's natural aspect ratio. Apply orientation-aware bounds rather than placing every image into one apparent box: landscape images may use up to 440px × 255px, portrait images up to 270px × 320px, and square images up to 320px × 320px. Never crop, stretch, or require per-card manual sizing.
- Treat these bounds as defaults, not locks: apply them only when the image has no explicit `width`, `height`, or inline `style` set. Never use CSS `!important` on an image's width or height. If the user later sets an image width or height in Anki, remove the default bounds for that image so the explicit per-card setting controls the final display size.
- Keep audio user-triggered rather than autoplaying.

## Images and audio

### Medical-image selection

Use externally sourced web images only. Never generate, draw, or synthesize an image for a card. Download/embed the selected image rather than hotlinking it, and put a compact source link on the back.

- **Cleveland Clinic first when accurate:** search Cleveland Clinic before other sources and use its image whenever it has a clear, medically accurate image that directly matches the card term or grouped terms. Do not use a Cleveland Clinic image merely because it is from Cleveland Clinic if the image does not actually depict the term.
- **Reliable fallback only:** if Cleveland Clinic has no accurate, usable match, use another reliable source such as a medical school, hospital, professional medical site, peer-reviewed paper, government health agency, OpenStax, NIH/NCI/NIDDK, or Wikimedia Commons with clear reuse terms. Avoid arbitrary unlicensed image-result thumbnails.
- **Direct semantic match:** choose the most typical, recognisable feature of the exact term—ideally a learner can see the image and recall the word. A merely related disease image is not sufficient. On a grouped card, the single image must support the whole contrast or synonym group.
- **Teaching clarity over visual appeal:** choose the image that best helps a medical student understand and remember the term. Prefer a prominent subject, adequate resolution, little or no text, little or no watermark, and avoid busy review figures, collages, or decorative stock photography.
- **No duplicate pictures:** use one distinct image per card. Do not reuse an image within the same deck unless the user explicitly asks for reuse. Before import, check both that every card has a unique image reference and that each image matches its card's word or grouped words.

Create one offline audio file per card. On macOS, prefer the local `Samantha` voice at a measured rate and convert to mono 22,050 Hz WAV. If local TTS is unavailable, use another authorized local TTS method; do not silently omit audio.

## Build and verify

For `.apkg` output, prepare a JSON specification and run:

```bash
python3 scripts/build_deck.py spec.json --output deck.apkg
```

The JSON object requires `deck_title` and `cards`. Each card requires `word`, `ipa`, `meaning`, `note_html`, `image`, `source_name`, and `source_url`; `audio_text` and `audio_path` are optional. `image` and `audio_path` are local paths. For grouped cards, use newline characters in `word`, `ipa`, and `meaning` so the entries align vertically. Use `audio_text` to read the grouped terms sequentially, and whenever the written front contains slashes, abbreviations, or punctuation that TTS should not read literally.

After building, verify that note count equals card count, every note has one audio reference and one image reference, all referenced media is embedded, every card image is unique and semantically appropriate, and the package opens as a valid zip/SQLite Anki package. Save the final `.apkg` in the user-requested location; otherwise use the current task's output directory. Copy to Downloads only when explicitly requested.

For a requested AnkiConnect import, perform the equivalent checks against the live notes and media after importing: exact target deck/subdeck, expected note count, one audio and one image per note, unique image references, linked source attribution, and successful scheduling/content verification. Do not replace a requested direct import with an `.apkg` file.
