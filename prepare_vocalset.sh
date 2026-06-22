#!/usr/bin/env bash
# Prepare VocalSet validation subset for relabelling:
# - 4 techniques: belt, breathy, straight, vibrato
# - 5 validation singers: f2, f8, m3, m5, m10

set -euo pipefail

VAL_SRC="${VAL_SRC:-$HOME/Downloads/SkyNote/OTHER_DATASETS/VOCALSET_data_versions/original_split/VocalSet_fixed/validation}"
RELABEL_ROOT="${RELABEL_ROOT:-$HOME/audio_new/VocalSet_relabel}"
SINGERS="f2 f8 m3 m5 m10"
TECHS="belt breathy straight vibrato"

if [[ ! -d "$VAL_SRC" ]]; then
  echo "Error: validation source not found: $VAL_SRC" >&2
  exit 1
fi

mkdir -p "$RELABEL_ROOT"
for tech in $TECHS; do
  rm -rf "$RELABEL_ROOT/$tech"
  mkdir -p "$RELABEL_ROOT/$tech"
  count=0
  for singer in $SINGERS; do
    for f in "$VAL_SRC/$tech"/${singer}_*.wav; do
      [[ -f "$f" ]] || continue
      ln -sf "$f" "$RELABEL_ROOT/$tech/$(basename "$f")"
      count=$((count + 1))
    done
  done
  echo "$tech: $count files"
done

total=$(find "$RELABEL_ROOT" -name '*.wav' | wc -l | tr -d ' ')
echo "Total: $total wav files in $RELABEL_ROOT"
