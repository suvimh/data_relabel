import os
import sys
import time
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)
import labelling_core as core

app = FastAPI(title="Audio Data Labelling API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory session state
session = {}


class StartRequest(BaseModel):
    data_dir: str
    window_size: float = Field(default=1.0, gt=0)
    hop_size: float = Field(default=0.5, gt=0)


class LabelAnnotation(BaseModel):
    state: Literal[0, 1]
    confidence: Optional[Literal[1, 2]] = None


class ConfirmRequest(BaseModel):
    annotations: dict[str, LabelAnnotation] = Field(default_factory=dict)


@app.get("/api/session/status")
def get_status():
    saved = core.load_session_state()
    has_session = saved is not None and bool(saved.get("audio_files"))
    safe_session = None
    if has_session:
        safe_session = {
            "window_size": saved.get("window_size", 1.0),
            "hop_size": saved.get("hop_size", 0.5),
        }
    return {"has_session": has_session, "session": safe_session}


@app.post("/api/session/start")
def start_session(req: StartRequest):
    global session
    if not req.data_dir or not os.path.isdir(req.data_dir):
        raise HTTPException(400, "Invalid directory path")

    core.clear_session_state()
    session, err = core.init_state(req.data_dir, req.window_size, req.hop_size)

    if err:
        session = {}
        raise HTTPException(400, err)
    if session.get("audio_data") is None:
        raise HTTPException(400, "No files to label")

    return core.get_progress(session)


@app.post("/api/session/resume")
def resume_session():
    global session
    saved = core.load_session_state()
    if not saved or not saved.get("audio_files"):
        raise HTTPException(400, "No saved session found")

    session, err = core.resume_state(saved)
    if err:
        raise HTTPException(400, err)
    if session.get("audio_data") is None:
        core.write_recording_key(
            session["data_dir"], session["valid_audio_files"], session["recording_ids"]
        )
        core.clear_session_state()
        return {**core.get_progress(session), "done": True}

    return {**core.get_progress(session), "done": False}


@app.post("/api/session/clear")
def clear_session():
    global session
    session = {}
    core.clear_session_state()
    return {"success": True}


@app.get("/api/segment/audio")
def get_audio():
    if session.get("audio_data") is None:
        raise HTTPException(400, "No active session")
    if not session.get("is_active"):
        raise HTTPException(400, "Session is not active")

    wav_bytes = core.get_current_segment_wav(session)
    if wav_bytes is None:
        raise HTTPException(400, "No audio segment available")

    return StreamingResponse(
        iter([wav_bytes]),
        media_type="audio/wav",
        headers={"Content-Disposition": "inline; filename=segment.wav"},
    )


@app.get("/api/segment/info")
def get_segment_info():
    if not session:
        raise HTTPException(400, "No active session")

    elapsed = time.time() - session.get("session_start_time", time.time())
    expired = elapsed >= core.MAX_SESSION_SECONDS
    progress = core.get_progress(session)
    return {**progress, "expired": expired, "done": False}


@app.post("/api/segment/confirm")
def confirm_segment(req: ConfirmRequest):
    global session
    if session.get("audio_data") is None:
        raise HTTPException(400, "No active session")

    expected_labels = set(session["labels"])
    submitted_labels = set(req.annotations)
    if submitted_labels != expected_labels:
        raise HTTPException(400, "Submit a present or absent state for every label.")
    for label, annotation in req.annotations.items():
        if annotation.state == 1 and annotation.confidence is None:
            raise HTTPException(400, f"Choose a confidence for {label}.")
        if annotation.state == 0 and annotation.confidence is not None:
            raise HTTPException(400, f"Confidence is only used for present labels ({label}).")

    recording_id = session["current_recording_id"]
    start = session["current_segment_start"]
    end = session["current_segment_end"]
    annotations = {
        label: {"state": value.state, "confidence": value.confidence}
        for label, value in req.annotations.items()
    }
    core.append_annotations(
        session["csv_path"], recording_id, start, end,
        annotations, session["labels"]
    )

    # check timeout
    elapsed = time.time() - session["session_start_time"]
    if elapsed >= core.MAX_SESSION_SECONDS:
        core.save_session_state(session)
        session["is_active"] = False
        return {"done": True, "timeout": True, "message": "Session timed out (20 min). Progress saved."}

    if not core.advance_segment(session):
        session["is_active"] = False
        core.write_recording_key(
            session["data_dir"], session["valid_audio_files"], session["recording_ids"]
        )
        core.clear_session_state()
        return {"done": True, "message": "All files labelled!"}

    return {**core.get_progress(session), "done": False}


@app.post("/api/segment/skip")
def skip_segment():
    global session
    if session.get("audio_data") is None:
        raise HTTPException(400, "No active session")

    elapsed = time.time() - session["session_start_time"]
    if elapsed >= core.MAX_SESSION_SECONDS:
        core.save_session_state(session)
        session["is_active"] = False
        return {"done": True, "timeout": True, "message": "Session timed out (20 min). Progress saved."}

    if not core.advance_segment(session):
        session["is_active"] = False
        core.write_recording_key(
            session["data_dir"], session["valid_audio_files"], session["recording_ids"]
        )
        core.clear_session_state()
        return {"done": True, "message": "All files labelled!"}

    return {**core.get_progress(session), "done": False}


@app.post("/api/session/save")
def save_session():
    global session
    if session.get("audio_data") is not None:
        core.save_session_state(session)
    return {"success": True}


@app.on_event("startup")
def startup():
    global session
    saved = core.load_session_state()
    if saved:
        session = saved
