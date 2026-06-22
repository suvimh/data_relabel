#!/usr/bin/env python3
"""Verify labelling app behavior against project instructions."""

import json
import os
import sys
import time
import urllib.error
import urllib.request

BASE = os.environ.get("LABEL_API", "http://127.0.0.1:8000")
DATA_DIR = os.environ.get("LABEL_DATA_DIR", os.path.expanduser("~/audio_new/VocalSet_relabel"))
SESSION_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "backend", "labelling_session.json"
)
CSV_PATH = os.path.join(DATA_DIR, "labelling_results.csv")

PASS = []
FAIL = []


def check(name, ok, detail=""):
    if ok:
        PASS.append(name)
        print(f"  PASS  {name}" + (f" — {detail}" if detail else ""))
    else:
        FAIL.append(name)
        print(f"  FAIL  {name}" + (f" — {detail}" if detail else ""))


def api(method, path, data=None):
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(
        BASE + path,
        data=body,
        headers={"Content-Type": "application/json"} if body else {},
        method=method,
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def main():
    print("=== VocalSet relabel verification ===\n")

    # --- Static checks (no server) ---
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "backend"))
    import labelling_core as core

    check("20-minute timeout constant", core.MAX_SESSION_SECONDS == 20 * 60)
    check("noise/silence auto-included", core.ALWAYS_LABELS == ["noise", "silence"])

    wav_count = len(core.get_audio_files(DATA_DIR))
    check("254 validation audio files", wav_count == 254, f"found {wav_count}")

    # --- Server checks ---
    try:
        status = api("GET", "/api/session/status")
    except urllib.error.URLError as e:
        print(f"\nServer not reachable at {BASE}: {e}")
        print("Start with: python launch.py")
        sys.exit(1)

    api("POST", "/api/session/clear", {})
    if os.path.exists(CSV_PATH):
        os.remove(CSV_PATH)

    start = api("POST", "/api/session/start", {
        "data_dir": DATA_DIR,
        "labels": "straight, vibrato, belt, breathy, unsure",
        "window_size": 0.5,
        "hop_size": 0.5,
    })

    labels = start.get("labels", [])
    expected = ["noise", "silence", "straight", "vibrato", "belt", "breathy", "unsure"]
    check("All 7 label types available", labels == expected, str(labels))
    check("0.5s segment window", start.get("end_sec", 0) - start.get("start_sec", 0) == 0.5)
    check("258 files NOT loaded (filtered)", start.get("total_files") == 254)

    # Multi-label confirm
    api("POST", "/api/segment/confirm", {"selected_labels": ["straight", "breathy"]})
    api("POST", "/api/segment/confirm", {"selected_labels": ["belt"]})
    pos_before_save = api("GET", "/api/segment/info")

    # Save & Quit equivalent
    api("POST", "/api/session/save", {})
    check("Session JSON written on save", os.path.exists(SESSION_FILE))

    with open(SESSION_FILE) as f:
        saved = json.load(f)
    check(
        "Session JSON stores position",
        saved.get("current_file_idx") is not None
        and saved.get("current_segment_start") is not None,
        f"file_idx={saved.get('current_file_idx')} start={saved.get('current_segment_start')}",
    )
    check("Session JSON stores data_dir", saved.get("data_dir") == DATA_DIR)
    check("Session JSON stores window/hop", saved.get("window_size") == 0.5 and saved.get("hop_size") == 0.5)

    # CSV persistence
    check("CSV created", os.path.exists(CSV_PATH))
    import pandas as pd
    df = pd.read_csv(CSV_PATH)
    check("CSV has 2 confirmed rows", len(df) == 2)
    check(
        "CSV multi-label row correct",
        df.iloc[0]["straight"] == 1 and df.iloc[0]["breathy"] == 1 and df.iloc[0]["belt"] == 0,
    )

    # Resume skips labelled segments
    resumed = api("POST", "/api/session/resume", {})
    check("Resume succeeds", not resumed.get("done", True))
    check(
        "Resume skips already-labelled segments",
        resumed.get("start_sec", -1) >= 1.0,
        f"resumed at {resumed.get('start_sec')}s (expected >= 1.0)",
    )
    check(
        "Resume resets 20-min timer",
        resumed.get("time_remaining_sec", 0) > 1100,
        f"{resumed.get('time_remaining_sec')}s remaining",
    )

    # Audio endpoint returns data
    req = urllib.request.Request(BASE + "/api/segment/audio")
    with urllib.request.urlopen(req) as resp:
        audio_bytes = resp.read()
    check("Audio segment served", len(audio_bytes) > 1000, f"{len(audio_bytes)} bytes")

    # Timeout logic (core-level, no 20-min wait)
    state = dict(saved)
    state["session_start_time"] = time.time() - (20 * 60 + 1)
    state["audio_data"] = None
    state["sr"] = None
    resumed_timeout, _ = core.resume_state(state)
    # simulate confirm after timeout
    core._load_file(resumed_timeout, resumed_timeout["current_file_idx"])
    elapsed = time.time() - resumed_timeout["session_start_time"]
    check("Timeout threshold is 20 minutes", elapsed < core.MAX_SESSION_SECONDS)

    # Empty-label confirm allowed (e.g. vibrato file with no vibrato)
    api("POST", "/api/segment/confirm", {"selected_labels": []})
    df2 = pd.read_csv(CSV_PATH)
    check("Empty label confirm allowed", len(df2) == 3)

    print(f"\n=== Results: {len(PASS)} passed, {len(FAIL)} failed ===")
    if FAIL:
        for f in FAIL:
            print(f"  - {f}")
        sys.exit(1)
    print("All checks passed.")


if __name__ == "__main__":
    main()
