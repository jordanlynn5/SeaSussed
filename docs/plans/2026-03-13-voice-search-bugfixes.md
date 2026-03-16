# Voice Search Bugfixes Plan

**Date:** 2026-03-13
**Research:** docs/research/2026-03-13-voice-search-bugs.md
**Status:** READY

## Summary

Three bugs in the voice session search/navigate flow:
1. Gemini calls `search_store` and `navigate_to_product` multiple times
2. `_find_product_url` matches wrong URLs to product names (cod → tilapia)
3. Double navigate triggers duplicate `POST /analyze/stream` calls

## Phases

| Phase | Description | Files | Status |
|---|---|---|---|
| 1 | Server-side tool call deduplication | `backend/voice_session.py`, `backend/tests/test_voice.py` | DONE |
| 2 | Fix `_find_product_url` with species-gated matching | `backend/voice_session.py`, `backend/tests/test_voice.py` | DONE |
| 3 | Client-side navigation guard | `extension/voice-client.js` | DONE |

Phases 1 and 2 touch the same files but different functions — they are **sequential** (not batch-eligible) to avoid merge conflicts.
Phase 3 is extension-only but depends on phase 1 conceptually (defense in depth).

## Phase Details

See phase files in `docs/plans/2026-03-13-voice-search-bugfixes-phases/`
