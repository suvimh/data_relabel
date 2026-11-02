import csv
import glob
import io
import json
import logging
import os
import secrets
import tempfile
import time

import librosa
import soundfile as sf


logger = logging.getLogger(__name__)
SESSION_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "labelling_session.json")
MAX_SESSION_SECONDS = 20 * 60
AUDIO_EXTENSIONS = ('*.wav', '*.mp3', '*.flac', '*.ogg', '*.m4a')
ANNOTATIONS_FILENAME = "labelling_annotations.csv"
RECORDING_KEY_FILENAME = "labelling_recording_key.csv"
LABEL_GROUPS = [
    {
        "dimension": "Pitch modulation",
        "labels": [
            {"key": "vibrato", "name": "Vibrato"},
            {"key": "straight", "name": "Straight"},
            {"key": "trill_upper_semitone", "name": "Trill (upper semitone)"},
            {"key": "trillo_goat_tone", "name": "Trillo (goat tone)"},
        ],
    },
    {
        "dimension": "Vocal production/timbre",
        "labels": [
            {"key": "belt", "name": "Belt"},
            {"key": "breathy", "name": "Breathy"},
            {"key": "inhaled", "name": "Inhaled"},
            {"key": "vocal_fry", "name": "Vocal fry"},
        ],
    },
    {
        "dimension": "Vocal mode/articulation",
        "labels": [
            {"key": "lip_trill", "name": "Lip trill"},
            {"key": "spoken", "name": "Spoken"},
        ],
    },
    {
        "dimension": "Other",
        "labels": [
            {"key": "silence", "name": "Silence"},
            {"key": "uncertain", "name": "Uncertain"},
            {"key": "noise", "name": "Noise"},
        ],
    },
]
LABELS = [label["key"] for group in LABEL_GROUPS for label in group["labels"]]
ANNOTATION_COLUMNS = (
    ["recording_id", "start_sec", "end_sec"]
    + [column for label in LABELS for column in (f"{label}_state", f"{label}_confidence")]
)


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
    serializable = {}
    for key, value in state_dict.items():
        if key in ('audio_data', 'sr'):
            continue
        try:
            json.dumps(value)
            serializable[key] = value
        except (TypeError, ValueError):
            pass
    with open(SESSION_FILE, 'w') as f:
        json.dump(serializable, f, indent=2)


def clear_session_state():
    if os.path.exists(SESSION_FILE):
        os.remove(SESSION_FILE)


def get_annotations_path(data_dir):
    return os.path.join(data_dir, ANNOTATIONS_FILENAME)


def get_recording_key_path(data_dir):
    return os.path.join(data_dir, RECORDING_KEY_FILENAME)


def _annotation_columns(labels):
    return (
        ["recording_id", "start_sec", "end_sec"]
        + [column for label in labels for column in (f"{label}_state", f"{label}_confidence")]
    )


def init_annotations_csv(csv_path, labels):
    columns = _annotation_columns(labels)
    if not os.path.exists(csv_path):
        with open(csv_path, "w", newline="") as f:
            csv.writer(f).writerow(columns)
        return

    with open(csv_path, newline="") as f:
        existing_columns = next(csv.reader(f), [])
    legacy_columns = _annotation_columns(
        ["unclear" if label == "uncertain" else label for label in labels]
    )
    if existing_columns == legacy_columns:
        unclear_state_idx = existing_columns.index("unclear_state")
        unclear_confidence_idx = existing_columns.index("unclear_confidence")
        existing_columns[unclear_state_idx] = "uncertain_state"
        existing_columns[unclear_confidence_idx] = "uncertain_confidence"
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                "w", newline="", dir=os.path.dirname(csv_path), delete=False
            ) as output:
                temp_path = output.name
                with open(csv_path, newline="") as source:
                    reader = csv.reader(source)
                    next(reader, None)
                    writer = csv.writer(output)
                    writer.writerow(existing_columns)
                    writer.writerows(reader)
            os.replace(temp_path, csv_path)
        finally:
            if temp_path and os.path.exists(temp_path):
                os.remove(temp_path)
        return
    if existing_columns != columns:
        raise ValueError(
            f"{csv_path} has a different annotation schema. Use the same label schema "
            "as the existing file or choose a new audio directory."
        )


def append_annotations(csv_path, recording_id, start_sec, end_sec, annotations, labels):
    row = {
        "recording_id": recording_id,
        "start_sec": round(start_sec, 3),
        "end_sec": round(end_sec, 3),
    }
    for label in labels:
        annotation = annotations[label]
        row[f"{label}_state"] = annotation["state"]
        row[f"{label}_confidence"] = (
            annotation["confidence"] if annotation["confidence"] is not None else ""
        )

    with open(csv_path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=_annotation_columns(labels))
        writer.writerow(row)


def get_annotated_segments(csv_path):
    if not os.path.exists(csv_path):
        return set()
    with open(csv_path, newline="") as f:
        reader = csv.DictReader(f)
        if not {"recording_id", "start_sec"}.issubset(reader.fieldnames or []):
            raise ValueError(f"{csv_path} does not have the expected annotation columns.")
        return {
            (row["recording_id"], round(float(row["start_sec"]), 3))
            for row in reader
        }


def _relative_file_key(filepath, data_dir):
    return os.path.relpath(filepath, data_dir)


def _new_recording_id(existing_ids):
    while True:
        recording_id = f"R-{secrets.token_hex(8).upper()}"
        if recording_id not in existing_ids:
            existing_ids.add(recording_id)
            return recording_id


def _get_recording_ids(data_dir, audio_files):
    relative_paths = [_relative_file_key(path, data_dir) for path in audio_files]
    existing_ids = set()
    return {
        key: _new_recording_id(existing_ids)
        for key in relative_paths
    }


def write_recording_key(data_dir, audio_files, recording_ids):
    path = get_recording_key_path(data_dir)
    file_exists = os.path.exists(path) and os.path.getsize(path) > 0
    if file_exists:
        with open(path, newline="") as f:
            columns = next(csv.reader(f), [])
        if columns != ["recording_id", "file"]:
            raise ValueError(f"{path} does not have the expected recording key columns.")
    with open(path, "a", newline="") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["recording_id", "file"])
        for audio_file in audio_files:
            file_key = _relative_file_key(audio_file, data_dir)
            writer.writerow([recording_ids[file_key], file_key])


def load_audio_file(filepath):
    y, sr = librosa.load(filepath, sr=None, mono=True)
    return y, sr


def get_segment_samples(audio_data, sr, start_sec, window_sec):
    start_sample = round(start_sec * sr)
    end_sample = round((start_sec + window_sec) * sr)
    return audio_data[start_sample:end_sample]


def segment_to_wav_bytes(segment, sr):
    buf = io.BytesIO()
    sf.write(buf, segment, sr, format='WAV')
    buf.seek(0)
    return buf.read()


def _load_file(state, idx):
    path = state['audio_files'][idx]
    y, sr = load_audio_file(path)
    state['audio_data'] = y
    state['sr'] = sr
    state['current_file_idx'] = idx
    state['current_segment_start'] = 0.0
    state['segment_num'] = 0
    state['file_duration'] = len(y) / sr
    file_key = _relative_file_key(path, state['data_dir'])
    state['current_recording_id'] = state['recording_ids'][file_key]
    state['current_segment_end'] = state['window_size']
    if path not in state['valid_audio_files']:
        state['valid_audio_files'].append(path)


def _load_next_complete_file(state, start_idx):
    idx = start_idx
    while idx < len(state['audio_files']):
        try:
            _load_file(state, idx)
        except (EOFError, OSError, ValueError, sf.SoundFileError):
            state['unreadable_file_count'] += 1
            idx += 1
            continue

        if state['file_duration'] < state['window_size']:
            state['short_file_count'] += 1
            idx += 1
            continue
        return True

    state['current_file_idx'] = len(state['audio_files'])
    state['audio_data'] = None
    state['sr'] = None
    state['file_duration'] = 0.0
    state['current_recording_id'] = ""
    return False


def advance_file(state):
    return _load_next_complete_file(state, state['current_file_idx'] + 1)


def advance_segment(state):
    next_start = round(state['current_segment_start'] + state['hop_size'], 9)
    file_duration = len(state['audio_data']) / state['sr']
    if next_start + state['window_size'] > file_duration + 1e-9:
        return advance_file(state)

    state['current_segment_start'] = next_start
    state['segment_num'] += 1
    state['current_segment_end'] = next_start + state['window_size']
    return True


def _advance_to_unannotated(state, annotated):
    while (
        state['audio_data'] is not None
        and (state['current_recording_id'], round(state['current_segment_start'], 3)) in annotated
    ):
        if not advance_segment(state):
            break


def init_state(data_dir, window_size, hop_size):
    files = get_audio_files(data_dir)
    if not files:
        return {}, "No audio files found in directory."
    secrets.SystemRandom().shuffle(files)

    labels = LABELS.copy()
    csv_path = get_annotations_path(data_dir)
    init_annotations_csv(csv_path, labels)
    recording_ids = _get_recording_ids(data_dir, files)
    state = {
        'labels': labels,
        'label_groups': LABEL_GROUPS,
        'audio_files': files,
        'recording_ids': recording_ids,
        'valid_audio_files': [],
        'unreadable_file_count': 0,
        'short_file_count': 0,
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
        'current_recording_id': '',
        'current_segment_end': 0.0,
    }

    if not _load_next_complete_file(state, 0):
        state['is_active'] = False
        return state, (
            "No readable audio files with complete windows were found "
            f"({state['unreadable_file_count']} unreadable, "
            f"{state['short_file_count']} shorter than the window)."
        )
    if state['unreadable_file_count'] or state['short_file_count']:
        logger.warning(
            "Skipped %d unreadable audio files and %d files shorter than the window.",
            state['unreadable_file_count'],
            state['short_file_count'],
        )

    annotated = get_annotated_segments(csv_path)
    _advance_to_unannotated(state, annotated)
    return state, None


def resume_state(saved_state):
    saved_state['session_start_time'] = time.time()
    saved_state['is_active'] = True
    saved_state['audio_data'] = None
    saved_state['sr'] = None
    saved_state['labels'] = LABELS.copy()
    saved_state['label_groups'] = LABEL_GROUPS
    saved_state.setdefault('valid_audio_files', [])
    saved_state.setdefault('unreadable_file_count', 0)
    saved_state.setdefault('short_file_count', 0)

    csv_path = get_annotations_path(saved_state['data_dir'])
    init_annotations_csv(csv_path, saved_state['labels'])
    saved_state['csv_path'] = csv_path

    if not saved_state.get('recording_ids'):
        saved_state['recording_ids'] = _get_recording_ids(
            saved_state['data_dir'], saved_state['audio_files']
        )

    if not saved_state['audio_files']:
        saved_state['is_active'] = False
        return saved_state, "No audio files are available to resume."

    saved_idx = saved_state['current_file_idx']
    if saved_idx >= len(saved_state['audio_files']):
        saved_idx = 0
    saved_start = saved_state.get('current_segment_start', 0.0)
    saved_segment_num = saved_state.get('segment_num', 0)
    try:
        _load_file(saved_state, saved_idx)
    except (EOFError, OSError, ValueError, sf.SoundFileError):
        saved_state['unreadable_file_count'] += 1
        has_complete_file = _load_next_complete_file(saved_state, saved_idx + 1)
    else:
        if saved_state['file_duration'] < saved_state['window_size']:
            saved_state['short_file_count'] += 1
            has_complete_file = _load_next_complete_file(saved_state, saved_idx + 1)
        elif saved_start + saved_state['window_size'] > saved_state['file_duration'] + 1e-9:
            has_complete_file = _load_next_complete_file(saved_state, saved_idx + 1)
        else:
            saved_state['current_segment_start'] = saved_start
            saved_state['segment_num'] = saved_segment_num
            saved_state['current_segment_end'] = saved_start + saved_state['window_size']
            has_complete_file = True

    if not has_complete_file:
        saved_state['is_active'] = False
        if saved_state['unreadable_file_count'] or saved_state['short_file_count']:
            return saved_state, (
                "No readable audio files with complete windows remain "
                f"({saved_state['unreadable_file_count']} unreadable, "
                f"{saved_state['short_file_count']} shorter than the window)."
            )
        return saved_state, None

    if saved_state['unreadable_file_count'] or saved_state['short_file_count']:
        logger.warning(
            "Skipped %d unreadable audio files and %d files shorter than the window.",
            saved_state['unreadable_file_count'],
            saved_state['short_file_count'],
        )

    annotated = get_annotated_segments(csv_path)
    _advance_to_unannotated(saved_state, annotated)
    return saved_state, None


def get_progress(state):
    remaining = max(0, MAX_SESSION_SECONDS - (time.time() - state['session_start_time']))
    return {
        'recording_id': state.get('current_recording_id', ''),
        'file_idx': state['current_file_idx'] + 1,
        'total_files': len(state['audio_files']),
        'segment_num': state['segment_num'] + 1,
        'start_sec': round(state['current_segment_start'], 3),
        'end_sec': round(state['current_segment_end'], 3),
        'file_duration': round(state.get('file_duration', 0), 3),
        'time_remaining_sec': int(remaining),
        'labels': state.get('labels', LABELS),
        'label_groups': state.get('label_groups', LABEL_GROUPS),
        'unreadable_file_count': state.get('unreadable_file_count', 0),
        'short_file_count': state.get('short_file_count', 0),
        'is_active': state.get('is_active', False),
    }


def get_current_segment_wav(state):
    if state['audio_data'] is None:
        return None
    segment = get_segment_samples(
        state['audio_data'], state['sr'],
        state['current_segment_start'], state['window_size']
    )
    return segment_to_wav_bytes(segment, state['sr'])
