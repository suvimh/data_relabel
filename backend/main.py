import os
import sys
import time
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

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
    labels: str
    window_size: float = 1.0
    hop_size: float = 0.5


class ConfirmRequest(BaseModel):
    selected_labels: list[str] = []


@app.get("/api/session/status")
def get_status():
    saved = core.load_session_state()
    has_session = saved is not None and bool(saved.get("audio_files"))
    return {"has_session": has_session, "session": saved}


@app.post("/api/session/start")
def start_session(req: StartRequest):
    global session
    if not req.data_dir or not os.path.isdir(req.data_dir):
        raise HTTPException(400, "Invalid directory path")

    core.clear_session_state()
    session, err = core.init_state(req.data_dir, req.labels, req.window_size, req.hop_size)

    if err:
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
        # all done
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

    fname = session["current_file_name"]
    start = session["current_segment_start"]
    end = session["current_segment_end"]

    selected = list(req.selected_labels) if req.selected_labels else []
    core.append_labels(
        session["csv_path"], fname, start, end,
        selected, session["labels"]
    )

    # check timeout
    elapsed = time.time() - session["session_start_time"]
    if elapsed >= core.MAX_SESSION_SECONDS:
        core.save_session_state(session)
        session["is_active"] = False
        return {"done": True, "timeout": True, "message": "Session timed out (20 min). Progress saved."}

    # advance
    if not core.advance_segment(session):
        # file done, try next
        if not core.advance_file(session):
            # all done
            session["is_active"] = False
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
        if not core.advance_file(session):
            session["is_active"] = False
            core.clear_session_state()
            return {"done": True, "message": "All files labelled!"}

    return {**core.get_progress(session), "done": False}


@app.post("/api/session/save")
def save_session():
    global session
    if session.get("audio_data") is not None:
        core.save_session_state(session)
    return {"success": True}


import os as os_mod
@app.on_event("startup")
def startup():
    global session
    saved = core.load_session_state()
    if saved:
        session = saved
