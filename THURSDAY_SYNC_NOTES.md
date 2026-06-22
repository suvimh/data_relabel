# Thursday Team Sync — Setup Notes (pubert)

Updated 2026-06-22 after full setup verification.

## Status: ready for test labelling before Thursday

| Item | Status |
|------|--------|
| Repo cloned | `/Users/pubert/audio_new/data_relabel` |
| Data prepared | `/Users/pubert/audio_new/VocalSet_relabel` — **254 files** |
| App runs | `python launch.py` → http://127.0.0.1:5173 |
| Automated checks | `python verify_setup.py` — 19/19 passed |

## Data setup

Run once (or after updating source data):

```bash
./prepare_vocalset.sh
```

This creates `~/audio_new/VocalSet_relabel` with per-file symlinks for:
- Techniques: `belt`, `breathy`, `straight`, `vibrato`
- Singers: `f2`, `f8`, `m3`, `m5`, `m10`

## App configuration

| Field | Value |
|-------|-------|
| Data Directory | `/Users/pubert/audio_new/VocalSet_relabel` |
| Custom Labels | `straight, vibrato, belt, breathy, unsure` |
| Window | `0.5` |
| Hop | `0.5` |

## Sample files for technique familiarization

- **belt:** `belt/f2_arpeggios_belt_a.wav`
- **breathy:** `breathy/f2_arpeggios_breathy_a.wav`
- **straight:** `straight/f2_arpeggios_straight_a.wav`
- **vibrato:** `vibrato/f2_arpeggios_vibrato_a.wav`

## Open questions for Thursday

1. **`unsure` vs empty labels:** When no technique applies, tick `unsure` or leave all unchecked?
2. **Skip behavior:** Skipped segments are not saved and reappear later — intentional?
3. **CSV collection:** How will individual `labelling_results.csv` files be merged for consensus?

## Output files

- Labels: `/Users/pubert/audio_new/VocalSet_relabel/labelling_results.csv`
- Session state: `backend/labelling_session.json` (gitignored)
