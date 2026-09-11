---
name: medterm-to-anki
description: Create or revise medical-English Anki cards in the user's minimal style. Use for medical vocabulary lists, lesson terminology, or requests for the user's preferred Anki style. Produces one card per input entry with General American IPA, offline macOS audio, concise Chinese explanations, and an optional Cleveland Clinic image. Import through AnkiConnect by default; create an .apkg only when explicitly requested. Do not use for general Anki troubleshooting.
---

# MedTerm to Anki

Create compact, medically accurate cards. Preserve every supplied input entry unless the user requests selection or deduplication. Ask for the destination deck/subdeck before importing if none is given. The default note type is `Minimal Vocabulary with Audio and Image v2`.

## Card contract

Create one forward card per note:

- Front: exactly one input entry as provided, a user-triggered pronunciation button, and matching General American IPA.
- Back: the Chinese meaning, one concise Memory Note, and, only when available, one medically relevant Cleveland Clinic image with linked attribution.
- Preserve the existing 20px grayscale light/dark layout, transparent image container, natural aspect ratio, and orientation-aware image bounds.
- Use American-English audio unless another variety is requested.

## Medical judgment

Make one independent card for every supplied input entry. Do not automatically split parenthetical abbreviations, slash-separated aliases, or synonyms; keep them on the same card. Split only when the user explicitly requests it or the input already contains separate entries. Preserve the supplied wording unless correction is needed for medical or linguistic accuracy.

Use the LLM for terminology interpretation, IPA, Chinese meaning, concise notes, medically specific Cleveland Clinic image queries, and final image/source judgment. Let `scripts/build_deck.py` handle deterministic formatting, escaping, paths, hashes, caches, TTS, concurrency, media, packaging, and validation.

## Media rules

Use images from Cleveland Clinic only; never use another website and never generate or synthesize an image. Search only Cleveland Clinic for each cache miss. Use an image only when it directly and accurately represents the medical entry and has adequate teaching value. Avoid decorative photos, busy collages, arbitrary thumbnails, and weak matches. If Cleveland Clinic has no suitable image, set `no_image: true` and create the card with empty Image and Source fields; do not continue searching elsewhere. Never reuse image content in the same deck unless requested.

Use cache-first image handling. The default cache is `~/.cache/medterm-to-anki/` (`audio/`, `images/`, `metadata/`); `MEDTERM_TO_ANKI_CACHE` or `--cache-dir` may override it. Image identity is the normalized full input entry plus normalized `image_query`; uncertainty is a cache miss. A valid negative cache means a successful Cleveland Clinic search confirmed no suitable image within the last 90 days; it may be reused until expiry. Every new term, expired negative entry, and uncertain result must be searched. Network errors, blocked downloads, empty/failed tool responses, or incomplete review are search failures—not evidence of no image—and must remain cache misses for later retry. Use `refresh_image_cache: true` to bypass either positive or negative cache. Never accept a weak image when a medically suitable candidate has not been found.

The script uses macOS offline `say` + `afconvert`, caches pronunciation-dependent output, and defaults to 8 concurrent TTS workers. Reduce with `--audio-workers` if the machine becomes unstable; do not replace this with network TTS.

## Workflow

1. Process the full input list in one semantic pass. Return compact structured JSON with one card per supplied input entry, all semantic content, and a stable, medically specific Cleveland Clinic `image_query` for every card. Do not spend turns narrating intermediate drafting.
2. Inspect the whole image cache and use the available web-search tool for misses in its largest supported parallel batches. Add returned official page URLs to each card's temporary `candidate_pages`, then run the bundled parallel candidate finder to open those pages and extract Cleveland Clinic image candidates concurrently. It also attempts its own site-restricted discovery, but `no-results` is not proof of no image. Medically judge candidates for every term individually. For each successfully completed search, either add `image`, `source_name`, and `source_url` for an approved Cleveland Clinic image, or set `no_image: true`, `no_image_reason: "confirmed_no_suitable_cleveland_image"`, and a timezone-aware ISO-8601 `image_search_checked_at`. A `search-failed`, `no-results`, or `incomplete` result cannot justify `no_image`: retry it with the available web-search tool and do not build/import while it remains unresolved. Do not search another source:

   ```bash
   python3 scripts/build_deck.py spec.json --inspect-image-cache
   python3 scripts/search_cleveland_images.py misses.json --output candidates.json --workers 8
   ```

   `search_cleveland_images.py` accepts optional `candidate_pages` arrays, opens cards and pages concurrently (default 8 workers), and permits only `clevelandclinic.org` page and image URLs in its output. Its candidates accelerate discovery but never replace medical review or proof that a no-image search completed successfully.

3. Build an explicitly requested package:

   ```bash
   python3 scripts/build_deck.py spec.json --output deck.apkg
   ```

4. For live AnkiConnect import, prepare deterministic media and fields first. The script prepares media in parallel where safe; the actual image web search remains tool-dependent:

   ```bash
   python3 scripts/build_deck.py spec.json --prepare-media prepared-media.json
   ```

   Upload the manifest rather than reconstructing paths, attribution, or HTML. Use one preparation/upload pass for the batch. Verify the exact deck/subdeck, note count, model compatibility, one audio per note, one distinct Cleveland Clinic image only where available, blank Image and Source fields for `no_image` cards, uploaded media, source links, and resulting content/scheduling.

## Spec fields

Each card requires `word`, `ipa`, `meaning`, and either `note` or backward-compatible `note_html`. `word` represents exactly one input entry and must contain no newline; parentheses, slashes, and synonyms within that entry are kept together. Repeated entries are allowed and receive separate stable card IDs. Use plain `note` by default. Optional fields: `semantic_identity` (only when the written front does not fully identify the medical concept), `audio_text` (acronyms, slashes, or punctuation), `audio_path` (user-supplied WAV), `refresh_image_cache`, and `no_image`. For a cache miss, provide either an approved Cleveland Clinic `image` with `source_name` and `source_url`, or the complete confirmed-no-image fields described above; never provide both. The source URL must use `clevelandclinic.org` or one of its subdomains.

Example:

```json
{"deck_title":"MT::示例","cards":[{"word":"fracture","ipa":"/.../","meaning":"骨折","note":"骨或软骨的连续性中断。","image_query":"site:clevelandclinic.org fracture medical illustration","no_image":true,"no_image_reason":"confirmed_no_suitable_cleveland_image","image_search_checked_at":"2026-09-11T12:00:00+08:00"}]}
```

Save `.apkg` files only to the user-named location or the current task output directory; copy to Downloads only when explicitly requested.
