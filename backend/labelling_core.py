import os
import json
import time
import glob
import io
import numpy as np
import pandas as pd
import librosa
import soundfile as sf

SESSION_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "labelling_session.json")
MAX_SESSION_SECONDS = 20 * 60
AUDIO_EXTENSIONS = ('*.wav', '*.mp3', '*.flac', '*.ogg', '*.m4a')
LABELS = ["straight", "vibrato", "belt", "breathy", "noise", "silence", "unsure"]


def sync_time_remaining(state):
    elapsed = time.time() - state.get('session_start_time', time.time())
    state['time_remaining_sec'] = max(0, int(MAX_SESSION_SECONDS - elapsed))
    return state['time_remaining_sec']


def restore_session_timer(state):
    remaining = state.get('time_remaining_sec', MAX_SESSION_SECONDS)
    remaining = max(0, min(MAX_SESSION_SECONDS, int(remaining)))
    state['session_start_time'] = time.time() - (MAX_SESSION_SECONDS - remaining)
    return remaining


def get_audio_files(data_dir):
    files = []
    for ext in AUDIO_EXTENSIONS:
        files.extend(glob.glob(os.path.join(data_dir, '**', ext), recursive=True))
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
    if 'session_start_time' in state_dict:
        sync_time_remaining(state_dict)
    serializable = {}
    for k, v in state_dict.items():
        if k in ('audio_data', 'sr'):
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


def load_audio_file(filepath):
    y, sr = librosa.load(filepath, sr=None, mono=True)
    return y, sr


def get_segment_samples(audio_data, sr, start_sec, window_sec):
    start_s = int(start_sec * sr)
    end_s = min(int((start_sec + window_sec) * sr), len(audio_data))
    return audio_data[start_s:end_s]


def segment_to_wav_bytes(segment, sr):
    buf = io.BytesIO()
    sf.write(buf, segment, sr, format='WAV')
    buf.seek(0)
    return buf.read()


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
    _load_file(state, state['current_file_idx'])
    return True


def _load_file(state, idx):
    path = state['audio_files'][idx]
    y, sr = load_audio_file(path)
    state['audio_data'] = y
    state['sr'] = sr
    state['current_segment_start'] = 0.0
    state['segment_num'] = 0
    state['current_segment_end'] = min(state['window_size'], len(y) / sr)
    state['file_duration'] = len(y) / sr
    state['current_file_name'] = os.path.relpath(path, state.get('data_dir', os.path.dirname(path)))


def init_state(data_dir, window_size, hop_size):
    labels = list(LABELS)

    files = get_audio_files(data_dir)
    csv_path = get_csv_path(data_dir)
    init_csv(csv_path, labels)

    state = {
        'labels': labels,
        'audio_files': files,
        'current_file_idx': 0,
        'current_segment_start': 0.0,
        'segment_num': 0,
        'audio_data': None,
        'sr': None,
        'session_start_time': time.time(),
        'time_remaining_sec': MAX_SESSION_SECONDS,
        'csv_path': csv_path,
        'data_dir': data_dir,
        'window_size': float(window_size),
        'hop_size': float(hop_size),
        'is_active': True,
        'file_duration': 0.0,
        'current_file_name': '',
        'current_segment_end': 0.0,
    }

    labeled = get_labeled_set(csv_path)

    if not files:
        state['is_active'] = False
        return state, "No audio files found in directory."

    _load_file(state, 0)

    fname = state['current_file_name']
    while (fname, round(state['current_segment_start'], 3)) in labeled:
        if not advance_segment(state):
            break
        fname = state.get('current_file_name', '')

    return state, None


def resume_state(saved_state):
    restore_session_timer(saved_state)
    saved_state['labels'] = list(LABELS)
    saved_state['is_active'] = True
    saved_state['audio_data'] = None
    saved_state['sr'] = None

    csv_path = get_csv_path(saved_state['data_dir'])
    saved_state['csv_path'] = csv_path
    labeled = get_labeled_set(csv_path)

    if saved_state['current_file_idx'] >= len(saved_state['audio_files']):
        saved_state['current_file_idx'] = 0
        saved_state['current_segment_start'] = 0.0

    try:
        _load_file(saved_state, saved_state['current_file_idx'])
    except (IndexError, FileNotFoundError):
        saved_state['is_active'] = False
        return saved_state, "Audio files not found."

    fname = saved_state['current_file_name']
    while (fname, round(saved_state['current_segment_start'], 3)) in labeled:
        if not advance_segment(saved_state):
            break
        fname = saved_state.get('current_file_name', '')

    return saved_state, None


def get_progress(state):
    remaining = max(0, MAX_SESSION_SECONDS - (time.time() - state['session_start_time']))
    return {
        'file_name': state.get('current_file_name', ''),
        'file_idx': state['current_file_idx'] + 1,
        'total_files': len(state['audio_files']),
        'segment_num': state['segment_num'] + 1,
        'start_sec': round(state['current_segment_start'], 3),
        'end_sec': round(state['current_segment_end'], 3),
        'file_duration': round(state.get('file_duration', 0), 3),
        'time_remaining_sec': int(remaining),
        'labels': state.get('labels', []),
        'is_active': state.get('is_active', False),
    }


def get_current_segment_wav(state):
    if state['audio_data'] is None:
        return None
    seg = get_segment_samples(
        state['audio_data'], state['sr'],
        state['current_segment_start'], state['window_size']
    )
    return segment_to_wav_bytes(seg, state['sr'])
