# Audio Data Labelling Tool

This application labels audio in short, overlapping segments. It runs a local
FastAPI backend and a React/Vite web interface.

## Requirements

- Python 3 and pip
- Node.js and npm
- A web browser
- Audio files in WAV, MP3, FLAC, OGG, or M4A format

## Setup

Activate your existing Conda environment from the repository root, then
install the backend dependencies into it:

```powershell
conda activate data_relabel_env
python -m pip install -r backend/requirements.txt
```

The activation command is the same in Anaconda Prompt, PowerShell, and
Linux/macOS terminals. If the backend dependencies are already installed in
this environment, you can skip the install command.

Install the frontend dependencies once:

```bash
cd frontend
npm ci
cd ..
```

Keep this Conda environment activated in the terminal when starting the app,
so `launch.py` uses its Python interpreter and installed backend dependencies.

## Launch

From the repository root, with `data_relabel_env` activated, run:

```bash
python launch.py
```

Open **http://127.0.0.1:5173** in your browser. The backend runs at
**http://127.0.0.1:8000**. Keep the terminal open while using the app; press
**Ctrl+C** there to stop both servers.

## Label audio

1. In **Data Directory**, enter the absolute path to the folder containing the
   audio files. The app searches that folder and its subfolders. The path must
   be accessible to the computer running the backend.
2. Set **Window (seconds)** to the segment duration and **Hop / Stride
   (seconds)** to the distance between segment starts. Defaults are 1.0 and
   0.5 seconds respectively.
3. Select **Start Labelling**. Files are presented in randomized order under
   anonymous recording IDs, not their original filenames. Listen to each
   segment and tick each label that applies. Unticked labels are recorded as
   absent (`0`); ticked labels are recorded as present (`1`). For every ticked
   label, choose **High (2)** or **Moderate (1)** confidence before confirming.
   Use the general **Uncertain** label when the window as a whole cannot be
   labelled reliably.
4. Choose **Skip** to move on without recording annotations for that segment.
   Choose **Save & Quit** to save the current position and return to setup.
   Use **Resume Previous Session** to continue a saved session.

Each labeling session is limited to 20 minutes. When the time expires, progress
is saved so you can resume. Do not move or rename the audio files while a
session is in progress.

### Label dimensions

| Dimension               | Labels                                                        |
| ----------------------- | ------------------------------------------------------------- |
| Pitch modulation        | Vibrato; Straight; Trill (upper semitone); Trillo (goat tone) |
| Vocal production/timbre | Belt; Breathy; Inhaled; Vocal fry                             |
| Vocal mode/articulation | Lip trill; Spoken                                             |
| Other                   | Silence; Uncertain; Noise                                    |

Confidence is recorded only for checked/present labels: `1` is moderate and
`2` is high. Do not use the recording key to guide annotations; it is intended
for comparison after the labeling pass.

The app drops trailing audio shorter than one full window; it does not pad
partial windows at the end of files.
Unreadable audio files (including empty, zero-byte files) and files shorter
than one window are skipped. The interface reports the counts without showing
the filenames to the annotator.

## Results and saved progress

- Annotations are appended to `labelling_annotations.csv` in the selected
  audio directory. Each row uses an anonymous `recording_id`, segment start
  and end times, and a state and confidence column for every label. Existing
  `unclear_state` and `unclear_confidence` columns are renamed to
  `uncertain_state` and `uncertain_confidence` the next time a labeling session
  starts, preserving the saved annotations.
- `labelling_recording_key.csv` maps anonymous IDs to original relative
  filenames. It is written only after all files have been processed, so it
  can be used to compare annotations with original metadata afterwards. Each
  new session gets fresh IDs; completed sessions append their key rows and
  annotations to the existing files.
- Resume information is stored in `backend/labelling_session.json`. Keep this
  file if you want to resume after restarting the app.
- Existing `labelling_results.csv` files from the older app are left
  untouched. The new annotation CSV must retain its fixed label schema.

## Troubleshooting

- If the app reports that no audio files were found, check the directory path
  and that it contains one of the supported audio formats.
- If Python reports a missing module, activate `data_relabel_env` and
  repeat the backend dependency installation command.
- If the frontend cannot start, confirm Node.js and npm are installed and run
  `npm ci` again from the `frontend` directory.
- The interactive API documentation is available at
  **http://127.0.0.1:8000/docs** while the backend is running.

## VocalSet relabelling:

belt, breathy, inhaled, lip trill, spoken, vibrato, straight, trill (upper semitone), trillo (goat tone), vocal fry

/media/suvihaara/upfHD/OTHER_DATASETS/VOCALSET_data_versions/VocalSet_fixed_relabel/test - manually relabelled/
