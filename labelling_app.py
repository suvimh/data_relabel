#!/usr/bin/env python3
"""
Audio Data Labelling Tool

Opens a Gradio web interface for labelling audio data.
Supports custom labels, configurable window sizes, session resume,
and a 20-minute fatigue timeout.
"""

import os
import json
import time
import glob
import threading
import numpy as np
import pandas as pd
import librosa
import gradio as gr

SESSION_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "labelling_session.json")
MAX_SESSION_SECONDS = 20 * 60
AUDIO_EXTENSIONS = ('*.wav', '*.mp3', '*.flac', '*.ogg', '*.m4a')

DEFAULT_LABELS_HELP = "belt, breathy, vibrato, straight"
ALWAYS_LABELS = ["noise", "silence"]


def get_audio_files(data_dir):
    files = []
    for ext in AUDIO_EXTENSIONS:
        files.extend(glob.glob(os.path.join(data_dir, ext)))
    return sorted([f for f in files if os.path.isfile(f)])


def load_session_state():
    if os.path.exists(SESSION_FILE):
        try:
            with open(SESSION_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return None


def save_session_state(state_dict):
    serializable = {}
    excluded = {'audio_data', 'sr'}
    for k, v in state_dict.items():
        if k in excluded:
            continue
        try:
            json.dumps(v)
            serializable[k] = v
        except (TypeError, ValueError):
            pass
    with open(SESSION_FILE, 'w') as f:
        json.dump(serializable, f, indent=2)


def clear_session_state():
    if os.path.exists(SESSION_FILE):
        os.remove(SESSION_FILE)


def get_csv_path(data_dir):
    return os.path.join(data_dir, "labelling_results.csv")


def init_csv(csv_path, labels):
    if not os.path.exists(csv_path):
        columns = ["file", "start_sec", "end_sec"] + labels
        pd.DataFrame(columns=columns).to_csv(csv_path, index=False)


def append_labels(csv_path, file_name, start_sec, end_sec, selected, all_labels):
    row = {"file": file_name, "start_sec": round(start_sec, 3), "end_sec": round(end_sec, 3)}
    for label in all_labels:
        row[label] = 1 if label in selected else 0
    pd.DataFrame([row]).to_csv(csv_path, mode='a', header=False, index=False)


def get_labeled_set(csv_path):
    if not os.path.exists(csv_path):
        return set()
    try:
        df = pd.read_csv(csv_path)
        return set(zip(df["file"], df["start_sec"]))
    except (pd.errors.EmptyDataError, KeyError):
        return set()


def format_time(seconds):
    m = int(seconds // 60)
    s = int(seconds % 60)
    return f"{m:02d}:{s:02d}"


def get_current_segment(state):
    if state['audio_data'] is None:
        return None
    sr = state['sr']
    start = state['current_segment_start']
    win = state['window_size']
    start_s = int(start * sr)
    end_s = min(int((start + win) * sr), len(state['audio_data']))
    return state['audio_data'][start_s:end_s]


def advance_segment(state):
    state['current_segment_start'] += state['hop_size']
    state['segment_num'] += 1
    file_dur = len(state['audio_data']) / state['sr']
    if state['current_segment_start'] >= file_dur:
        return advance_file(state)
    state['current_segment_end'] = min(
        state['current_segment_start'] + state['window_size'],
        file_dur
    )
    return True


def advance_file(state):
    state['current_file_idx'] += 1
    state['current_segment_start'] = 0.0
    state['segment_num'] = 0
    if state['current_file_idx'] >= len(state['audio_files']):
        return False
    load_file(state, state['current_file_idx'])
    return True


def load_file(state, idx):
    path = state['audio_files'][idx]
    y, sr = librosa.load(path, sr=None, mono=True)
    state['audio_data'] = y
    state['sr'] = sr
    state['current_segment_start'] = 0.0
    state['segment_num'] = 0
    state['current_segment_end'] = min(
        state['window_size'],
        len(y) / sr
    )
    state['file_duration'] = len(y) / sr
    state['current_file_name'] = os.path.basename(path)


def build_info_text(state):
    total = len(state['audio_files'])
    idx = state['current_file_idx'] + 1
    fname = state.get('current_file_name', '')
    seg = state['segment_num'] + 1
    start = state['current_segment_start']
    end = state['current_segment_end']
    fdur = state.get('file_duration', 0)

    elapsed = time.time() - state['session_start_time']
    remaining = max(0, MAX_SESSION_SECONDS - elapsed)

    lines = [
        f"**File {idx}/{total}:** `{fname}` ({fdur:.2f}s)",
        f"**Segment {seg}:** {start:.2f}s – {end:.2f}s",
        f"**Session time remaining:** {format_time(remaining)}"
    ]
    return "\n\n".join(lines)


def time_expired(state):
    elapsed = time.time() - state['session_start_time']
    return elapsed >= MAX_SESSION_SECONDS


# ---- Gradio callbacks ----

def on_start(data_dir, custom_labels, window_size, hop_size, state_dict):
    labels = ALWAYS_LABELS + [l.strip() for l in custom_labels.split(",") if l.strip()]
    labels = list(dict.fromkeys(labels))

    if not os.path.isdir(data_dir):
        return (
            gr.update(visible=True),
            gr.update(visible=False),
            gr.update(visible=False),
            gr.update("### Configuration\n\nError: directory does not exist."),
            gr.update(visible=False),
            gr.update(visible=False),
            None,
            gr.update(choices=[], value=[]),
            state_dict,
        )

    files = get_audio_files(data_dir)
    if not files:
        return (
            gr.update(visible=True),
            gr.update(visible=False),
            gr.update(visible=False),
            gr.update("### Configuration\n\nError: no audio files found in directory."),
            gr.update(visible=False),
            gr.update(visible=False),
            None,
            gr.update(choices=[], value=[]),
            state_dict,
        )

    csv_path = get_csv_path(data_dir)
    init_csv(csv_path, labels)

    labeled = get_labeled_set(csv_path)

    new_state = {
        'labels': labels,
        'audio_files': files,
        'current_file_idx': 0,
        'current_segment_start': 0.0,
        'segment_num': 0,
        'audio_data': None,
        'sr': None,
        'session_start_time': time.time(),
        'csv_path': csv_path,
        'data_dir': data_dir,
        'window_size': float(window_size),
        'hop_size': float(hop_size),
        'is_active': True,
        'file_duration': 0.0,
        'current_file_name': '',
        'current_segment_end': 0.0,
    }

    load_file(new_state, 0)

    # skip already-labeled segments
    fname = new_state['current_file_name']
    while (fname, round(new_state['current_segment_start'], 3)) in labeled:
        if not advance_segment(new_state):
            break
        fname = new_state.get('current_file_name', '')

    if new_state['audio_data'] is None:
        return (
            gr.update(visible=False),
            gr.update(visible=False),
            gr.update(visible=True),
            gr.update("### All files already labeled!"),
            gr.update(visible=False),
            gr.update(visible=False),
            None,
            gr.update(choices=[], value=[]),
            new_state,
        )

    seg = get_current_segment(new_state)
    seg_audio = (new_state['sr'], seg.astype(np.float32)) if seg is not None else None

    info = build_info_text(new_state)

    return (
        gr.update(visible=False),
        gr.update(visible=True),
        gr.update(visible=False),
        info,
        gr.update(visible=False),
        gr.update(visible=False),
        seg_audio,
        gr.update(choices=new_state['labels'], value=[]),
        new_state,
    )


def on_confirm(selected_labels, state_dict):
    if not state_dict.get('is_active') or state_dict['audio_data'] is None:
        return (
            gr.update(),
            gr.update(),
            gr.update(),
            None,
            gr.update(value=[], choices=[]),
            state_dict,
        )

    state = state_dict
    fname = state['current_file_name']
    start = state['current_segment_start']
    end = state['current_segment_end']

    # save the label row
    selected = list(selected_labels) if selected_labels else []
    append_labels(state['csv_path'], fname, start, end, selected, state['labels'])

    # check time expiry
    if time_expired(state):
        save_session_state(state)
        return (
            gr.update(visible=True),
            gr.update(visible=False),
            gr.update(),
            None,
            gr.update(value=[], choices=[]),
            state,
        )

    # advance
    if not advance_segment(state):
        # file finished, try next
        if not advance_file(state):
            # all done
            clear_session_state()
            return (
                gr.update(visible=False),
                gr.update(visible=False),
                gr.update(visible=True),
                None,
                gr.update(value=[], choices=[]),
                state,
            )

    seg = get_current_segment(state)
    seg_audio = (state['sr'], seg.astype(np.float32)) if seg is not None else None
    info = build_info_text(state)

    return (
        gr.update(value=info),
        gr.update(visible=False),
        gr.update(visible=False),
        seg_audio,
        gr.update(value=[], choices=state['labels']),
        state,
    )


def on_skip(state_dict):
    if not state_dict.get('is_active') or state_dict['audio_data'] is None:
        return (
            gr.update(),
            gr.update(),
            None,
            gr.update(value=[], choices=[]),
            state_dict,
        )

    state = state_dict

    if time_expired(state):
        save_session_state(state)
        return (
            gr.update(visible=True),
            gr.update(visible=False),
            None,
            gr.update(value=[], choices=[]),
            state,
        )

    if not advance_segment(state):
        if not advance_file(state):
            clear_session_state()
            return (
                gr.update(visible=False),
                gr.update(visible=True),
                None,
                gr.update(value=[], choices=[]),
                state,
            )

    seg = get_current_segment(state)
    seg_audio = (state['sr'], seg.astype(np.float32)) if seg is not None else None
    info = build_info_text(state)

    return (
        gr.update(value=info),
        gr.update(visible=False),
        seg_audio,
        gr.update(value=[], choices=state['labels']),
        state,
    )


def on_quit(state_dict):
    if state_dict.get('is_active'):
        save_session_state(state_dict)
    clear_state = {
        'labels': [],
        'audio_files': [],
        'current_file_idx': 0,
        'current_segment_start': 0.0,
        'segment_num': 0,
        'audio_data': None,
        'sr': None,
        'session_start_time': None,
        'csv_path': '',
        'data_dir': '',
        'window_size': 1.0,
        'hop_size': 0.5,
        'is_active': False,
        'file_duration': 0.0,
        'current_file_name': '',
        'current_segment_end': 0.0,
    }
    return (
        gr.update(visible=True),
        gr.update(visible=False),
        gr.update(visible=False),
        None,
        gr.update(value=[], choices=[]),
        gr.update(value=""),
        gr.update(value=""),
        gr.update(value=1.0),
        gr.update(value=0.5),
        clear_state,
    )


def on_finish_new():
    clear_session_state()
    clear_state = {
        'labels': [],
        'audio_files': [],
        'current_file_idx': 0,
        'current_segment_start': 0.0,
        'segment_num': 0,
        'audio_data': None,
        'sr': None,
        'session_start_time': None,
        'csv_path': '',
        'data_dir': '',
        'window_size': 1.0,
        'hop_size': 0.5,
        'is_active': False,
        'file_duration': 0.0,
        'current_file_name': '',
        'current_segment_end': 0.0,
    }
    return (
        gr.update(visible=True),
        gr.update(visible=False),
        gr.update(visible=False),
        gr.update(""),
        gr.update(visible=False),
        gr.update(visible=False),
        None,
        gr.update(value=[], choices=[]),
        clear_state,
    )


def on_resume(state_dict):
    if not state_dict.get('labels'):
        # no valid session
        return (
            gr.update(visible=True),
            gr.update(visible=False),
            gr.update(visible=False),
            gr.update("### Resume failed: no saved session found."),
            gr.update(visible=False),
            gr.update(visible=False),
            None,
            gr.update(value=[], choices=[]),
            state_dict,
        )

    state = state_dict
    state['session_start_time'] = time.time()
    state['is_active'] = True

    # check if the current file index is valid
    if state['current_file_idx'] >= len(state['audio_files']):
        state['current_file_idx'] = 0
        state['current_segment_start'] = 0.0

    csv_path = get_csv_path(state['data_dir'])
    state['csv_path'] = csv_path
    labeled = get_labeled_set(csv_path)

    try:
        load_file(state, state['current_file_idx'])
    except (IndexError, FileNotFoundError):
        return (
            gr.update(visible=True),
            gr.update(visible=False),
            gr.update(visible=False),
            gr.update("### Resume failed: audio files not found."),
            gr.update(visible=False),
            gr.update(visible=False),
            None,
            gr.update(value=[], choices=[]),
            state,
        )

    # skip already-labeled segments
    fname = state['current_file_name']
    while (fname, round(state['current_segment_start'], 3)) in labeled:
        if not advance_segment(state):
            break
        fname = state.get('current_file_name', '')

    if state['audio_data'] is None:
        return (
            gr.update(visible=False),
            gr.update(visible=False),
            gr.update(visible=True),
            gr.update("### All files already labeled!"),
            gr.update(visible=False),
            gr.update(visible=False),
            None,
            gr.update(value=[], choices=[]),
            state,
        )

    seg = get_current_segment(state)
    seg_audio = (state['sr'], seg.astype(np.float32)) if seg is not None else None
    info = build_info_text(state)

    return (
        gr.update(visible=False),
        gr.update(visible=True),
        gr.update(visible=False),
        info,
        gr.update(visible=False),
        gr.update(visible=False),
        seg_audio,
        gr.update(choices=state['labels'], value=[]),
        state,
    )


def on_load_app():
    session = load_session_state()
    if session and session.get('labels') and session.get('audio_files'):
        resume_msg = (
            "### Previous session found!\n\n"
            f"Directory: `{session.get('data_dir', '?')}`\n"
            f"Labels: {', '.join(session.get('labels', []))}\n"
            f"File {session.get('current_file_idx', 0) + 1}/{len(session.get('audio_files', []))}\n\n"
            "Click **Resume** to continue or **Start Fresh** to begin a new session."
        )
        return (
            gr.update(visible=True),
            gr.update(value=resume_msg, visible=True),
            gr.update(visible=True),
            gr.update(visible=True),
            gr.update(value=session.get('data_dir', '')),
            gr.update(value=", ".join(
                [l for l in session.get('labels', []) if l not in ALWAYS_LABELS]
            )),
            gr.update(value=session.get('window_size', 1.0)),
            gr.update(value=session.get('hop_size', 0.5)),
            session,
        )
    return (
        gr.update(visible=True),
        gr.update(visible=False),
        gr.update(visible=False),
        gr.update(visible=False),
        gr.update(value=""),
        gr.update(value=""),
        gr.update(value=1.0),
        gr.update(value=0.5),
        {
            'labels': [],
            'audio_files': [],
            'current_file_idx': 0,
            'current_segment_start': 0.0,
            'segment_num': 0,
            'audio_data': None,
            'sr': None,
            'session_start_time': None,
            'csv_path': '',
            'data_dir': '',
            'window_size': 1.0,
            'hop_size': 0.5,
            'is_active': False,
            'file_duration': 0.0,
            'current_file_name': '',
            'current_segment_end': 0.0,
        },
    )


def build_app():
    with gr.Blocks(title="Audio Data Labelling") as app:
        gr.Markdown("# Audio Data Labelling Tool")

        state = gr.State({
            'labels': [],
            'audio_files': [],
            'current_file_idx': 0,
            'current_segment_start': 0.0,
            'segment_num': 0,
            'audio_data': None,
            'sr': None,
            'session_start_time': None,
            'csv_path': '',
            'data_dir': '',
            'window_size': 1.0,
            'hop_size': 0.5,
            'is_active': False,
            'file_duration': 0.0,
            'current_file_name': '',
            'current_segment_end': 0.0,
        })

        # --- Config Panel ---
        with gr.Group(visible=True, elem_id="config-panel") as config_panel:
            gr.Markdown("### Configuration")
            data_dir = gr.Textbox(
                label="Data Directory",
                placeholder="/path/to/your/audio/files",
                info="Path to the folder containing audio files"
            )
            labels_input = gr.Textbox(
                label="Custom Labels (comma-separated)",
                placeholder=DEFAULT_LABELS_HELP,
                info="'noise' and 'silence' are always added automatically"
            )
            window_size = gr.Number(label="Window Size (seconds)", value=1.0, minimum=0.1, step=0.1)
            hop_size = gr.Number(label="Hop / Stride (seconds)", value=0.5, minimum=0.1, step=0.1)

            resume_info = gr.Markdown("", visible=False)

            with gr.Row():
                start_btn = gr.Button("Start Labelling", variant="primary", size="lg")
                resume_btn = gr.Button("Resume Previous Session", variant="secondary", visible=False, size="lg")
                new_btn = gr.Button("Start Fresh", variant="secondary", visible=False, size="lg")

            with gr.Row():
                quit_from_config = gr.Button("Clear Saved Session", variant="stop", size="sm")

        # --- Labelling Panel ---
        with gr.Group(visible=False, elem_id="label-panel") as label_panel:
            info_text = gr.Markdown("Ready")

            audio_player = gr.Audio(
                label="Audio Segment",
                type="numpy",
                interactive=False,
                autoplay=True,
            )

            label_selector = gr.CheckboxGroup(
                label="Select Labels",
                choices=[],
                interactive=True,
            )

            with gr.Row():
                confirm_btn = gr.Button("Confirm Labels", variant="primary", size="lg")
                skip_btn = gr.Button("Skip", size="lg")
                quit_btn = gr.Button("Save & Quit", variant="stop", size="lg")

        # --- Summary Panel ---
        with gr.Group(visible=False, elem_id="summary-panel") as summary_panel:
            gr.Markdown("### Labelling Complete")
            summary_text = gr.Markdown("All files have been labelled.")
            finish_btn = gr.Button("Start New Session", variant="primary", size="lg")

        # ---- Wire up callbacks ----

        start_btn.click(
            fn=on_start,
            inputs=[data_dir, labels_input, window_size, hop_size, state],
            outputs=[config_panel, label_panel, summary_panel, info_text,
                     resume_info, resume_btn, audio_player, label_selector, state],
        )

        confirm_btn.click(
            fn=on_confirm,
            inputs=[label_selector, state],
            outputs=[info_text, config_panel, summary_panel, audio_player,
                     label_selector, state],
        )

        skip_btn.click(
            fn=on_skip,
            inputs=[state],
            outputs=[info_text, summary_panel, audio_player, label_selector, state],
        )

        quit_btn.click(
            fn=on_quit,
            inputs=[state],
            outputs=[config_panel, label_panel, summary_panel, audio_player,
                     label_selector, data_dir, labels_input, window_size, hop_size, state],
        )

        finish_btn.click(
            fn=on_finish_new,
            inputs=[],
            outputs=[config_panel, label_panel, summary_panel, info_text,
                     resume_info, resume_btn, audio_player, label_selector, state],
        )

        resume_btn.click(
            fn=on_resume,
            inputs=[state],
            outputs=[config_panel, label_panel, summary_panel, info_text,
                     resume_info, resume_btn, audio_player, label_selector, state],
        )

        new_btn.click(
            fn=on_finish_new,
            inputs=[],
            outputs=[config_panel, label_panel, summary_panel, info_text,
                     resume_info, resume_btn, audio_player, label_selector, state],
        )

        def on_clear_session():
            clear_session_state()
            empty = {
                'labels': [],
                'audio_files': [],
                'current_file_idx': 0,
                'current_segment_start': 0.0,
                'segment_num': 0,
                'audio_data': None,
                'sr': None,
                'session_start_time': None,
                'csv_path': '',
                'data_dir': '',
                'window_size': 1.0,
                'hop_size': 0.5,
                'is_active': False,
                'file_duration': 0.0,
                'current_file_name': '',
                'current_segment_end': 0.0,
            }
            return (
                gr.update(visible=False),
                gr.update(visible=False),
                gr.update("### Session cleared."),
                empty,
            )

        quit_from_config.click(
            fn=on_clear_session,
            inputs=[],
            outputs=[resume_info, resume_btn, info_text, state],
        )

        app.load(
            fn=on_load_app,
            inputs=[],
            outputs=[config_panel, resume_info, resume_btn, new_btn,
                     data_dir, labels_input, window_size, hop_size, state],
        )

    return app


if __name__ == "__main__":
    app = build_app()
    app.launch(inbrowser=True, show_error=True, theme=gr.themes.Soft())
