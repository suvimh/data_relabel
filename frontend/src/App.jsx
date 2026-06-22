import { useState, useEffect, useCallback, useRef } from 'react'
import * as api from './api'

const MAX_SESSION_SECONDS = 20 * 60
const PRESET_LABELS = ['straight', 'vibrato', 'belt', 'breathy', 'noise', 'silence', 'unsure']

export default function App() {
  const [step, setStep] = useState('loading') // loading | setup | labelling | summary
  const [session, setSession] = useState(null)
  const [progress, setProgress] = useState(null)
  const [audioUrl, setAudioUrl] = useState(null)
  const [message, setMessage] = useState('')
  const [timeLeft, setTimeLeft] = useState(MAX_SESSION_SECONDS)
  const audioRef = useRef(null)

  // Check for saved session on mount
  useEffect(() => {
    api.getStatus().then((data) => {
      if (data.has_session) {
        setSession(data.session)
        setStep('setup')
      } else {
        setStep('setup')
      }
    })
  }, [])

  // Countdown timer during labelling
  useEffect(() => {
    if (step !== 'labelling' || !session?.session_start_time) return
    const id = setInterval(() => {
      const elapsed = (Date.now() / 1000) - session.session_start_time
      const remaining = Math.max(0, MAX_SESSION_SECONDS - elapsed)
      setTimeLeft(remaining)
      if (remaining <= 0) handleTimeout()
    }, 1000)
    return () => clearInterval(id)
  }, [step, session])

  const handleTimeout = useCallback(async () => {
    await api.saveSession()
    setMessage('Session timed out (20 min). Progress saved.')
    setStep('setup')
    setAudioUrl(null)
  }, [])

  async function handleStart(dataDir, windowSize, hopSize) {
    try {
      const prog = await api.startSession(dataDir, windowSize, hopSize)
      const remaining = prog.time_remaining_sec ?? MAX_SESSION_SECONDS
      setProgress(prog)
      setTimeLeft(remaining)
      setSession(prev => ({
        ...prev,
        session_start_time: Date.now() / 1000 - (MAX_SESSION_SECONDS - remaining),
      }))
      setAudioUrl(api.getSegmentAudioUrl() + '?t=' + Date.now())
      setStep('labelling')
      setMessage('')
    } catch (e) {
      setMessage(e.message)
    }
  }

  async function handleResume() {
    try {
      const prog = await api.resumeSession()
      const remaining = prog.time_remaining_sec ?? MAX_SESSION_SECONDS
      setProgress(prog)
      setTimeLeft(remaining)
      setSession(prev => ({
        ...prev,
        session_start_time: Date.now() / 1000 - (MAX_SESSION_SECONDS - remaining),
      }))
      if (prog.done) {
        setMessage(prog.message || 'All files labelled!')
        setStep('summary')
        return
      }
      setAudioUrl(api.getSegmentAudioUrl() + '?t=' + Date.now())
      setStep('labelling')
      setMessage('')
    } catch (e) {
      setMessage(e.message)
    }
  }

  async function handleConfirm(selected) {
    try {
      const res = await api.confirmLabels(selected || [])
      if (res.done) {
        setAudioUrl(null)
        setProgress(null)
        setMessage(res.message || 'Done')
        setStep('summary')
        return
      }
      setProgress(res)
      setAudioUrl(api.getSegmentAudioUrl() + '?t=' + Date.now())
    } catch (e) {
      setMessage(e.message)
    }
  }

  async function handleSkip() {
    try {
      const res = await api.skipSegment()
      if (res.done) {
        setAudioUrl(null)
        setProgress(null)
        setMessage(res.message || 'Done')
        setStep('summary')
        return
      }
      setProgress(res)
      setAudioUrl(api.getSegmentAudioUrl() + '?t=' + Date.now())
    } catch (e) {
      setMessage(e.message)
    }
  }

  async function handleSaveQuit() {
    if (session) await api.saveSession()
    setAudioUrl(null)
    setProgress(null)
    setMessage('Session saved. You can resume later.')
    setStep('setup')
  }

  if (step === 'loading') {
    return <div className="container"><p>Loading...</p></div>
  }

  if (step === 'setup') {
    return (
      <SetupPanel
        hasSession={!!session?.audio_files?.length}
        session={session}
        message={message}
        onStart={handleStart}
        onResume={handleResume}
      />
    )
  }

  if (step === 'labelling' && progress) {
    return (
      <LabellingPanel
        progress={progress}
        audioUrl={audioUrl}
        timeLeft={timeLeft}
        onConfirm={handleConfirm}
        onSkip={handleSkip}
        onQuit={handleSaveQuit}
      />
    )
  }

  if (step === 'summary') {
    return (
      <SummaryPanel
        message={message}
        onNew={() => {
          api.clearSession()
          setSession(null)
          setProgress(null)
          setMessage('')
          setStep('setup')
        }}
      />
    )
  }

  return <div className="container"><p>Loading...</p></div>
}

function SetupPanel({ hasSession, session, message, onStart, onResume }) {
  const [dataDir, setDataDir] = useState(session?.data_dir || '')
  const [windowSize, setWindowSize] = useState(session?.window_size ?? 0.5)
  const [hopSize, setHopSize] = useState(session?.hop_size ?? 0.5)

  function handleSubmit(e) {
    e.preventDefault()
    if (!dataDir.trim()) return
    onStart(dataDir.trim(), windowSize, hopSize)
  }

  return (
    <div className="container">
      <h1>Audio Data Labelling Tool</h1>

      <div className="instructions">
        <h2>How to use this app</h2>
        <ol>
          <li>Set <strong>Data Directory</strong> to your parent folder of audio files (e.g. VocalSet relabel folder).</li>
          <li>Use <strong>Window</strong> and <strong>Hop</strong> of <code>0.5</code> for 0.5-second segments.</li>
          <li>Click <strong>Start Labelling</strong> for a fresh run (clears previous CSV results), or <strong>Resume Previous Session</strong> to continue.</li>
          <li>Listen to each clip, tick <em>every</em> label that applies, then click <strong>Confirm Labels</strong>.</li>
          <li>Use <strong>Save &amp; Quit</strong> when done — your place and timer are saved. Sessions auto-stop after 20 minutes.</li>
        </ol>
        <p>
          <strong>Tip:</strong> Folder names are hints, not ground truth. A file in <code>straight</code> can also sound <code>breathy</code> — tick both. A <code>vibrato</code> file may have segments without vibrato — leave it unchecked.
        </p>
        <p>
          <strong>Your labels are saved to</strong> <code>{'{data_dir}'}/labelling_results.csv</code> (not the session file in the repo).
        </p>
        <div className="label-guide">
          <strong>What to listen for</strong>
          <dl>
            <dt>straight</dt><dd>Steady tone, little pitch wobble</dd>
            <dt>vibrato</dt><dd>Regular pitch pulsation on sustained notes</dd>
            <dt>belt</dt><dd>Loud, powerful, chest-forward singing</dd>
            <dt>breathy</dt><dd>Audible air in the tone</dd>
            <dt>noise / silence</dt><dd>Non-vocal noise or quiet gaps</dd>
            <dt>unsure</dt><dd>Use when you genuinely cannot tell</dd>
          </dl>
        </div>
      </div>

      <form onSubmit={handleSubmit} className="panel">
        <h2>Configuration</h2>

        <label>
          Data Directory
          <input
            type="text"
            value={dataDir}
            onChange={e => setDataDir(e.target.value)}
            placeholder="/Users/you/audio_new/VocalSet_relabel"
            required
          />
        </label>

        <div className="preset-labels">
          <span className="preset-labels-title">Labels (fixed)</span>
          <div className="preset-labels-list">
            {PRESET_LABELS.map(label => (
              <span key={label} className="preset-label-chip">{label}</span>
            ))}
          </div>
        </div>

        <div className="row">
          <label>
            Window (seconds)
            <input
              type="number"
              value={windowSize}
              onChange={e => setWindowSize(parseFloat(e.target.value) || 1)}
              min="0.1"
              step="0.1"
            />
          </label>
          <label>
            Hop / Stride (seconds)
            <input
              type="number"
              value={hopSize}
              onChange={e => setHopSize(parseFloat(e.target.value) || 0.5)}
              min="0.1"
              step="0.1"
            />
          </label>
        </div>

        {message && <p className="error">{message}</p>}

        <div className="buttons">
          <button type="submit" className="primary">Start Labelling</button>
          {hasSession && (
            <button type="button" onClick={onResume} className="secondary">
              Resume Previous Session
            </button>
          )}
        </div>
      </form>
    </div>
  )
}

function LabellingPanel({ progress, audioUrl, timeLeft, onConfirm, onSkip, onQuit }) {
  const [selected, setSelected] = useState([])

  const mins = Math.floor(timeLeft / 60)
  const secs = Math.floor(timeLeft % 60)

  function handleToggle(label) {
    setSelected(prev =>
      prev.includes(label)
        ? prev.filter(l => l !== label)
        : [...prev, label]
    )
  }

  useEffect(() => { setSelected([]) }, [audioUrl])

  return (
    <div className="container">
      <h1>Audio Data Labelling</h1>

      <div className="panel">
        <div className="progress-bar">
          <div className="progress-fill" style={{ width: `${(progress.file_idx / progress.total_files) * 100}%` }} />
        </div>

        <div className="info-grid">
          <div>
            <strong>File</strong> {progress.file_idx}/{progress.total_files}
            <br /><code>{progress.file_name}</code> ({progress.file_duration}s)
          </div>
          <div>
            <strong>Segment</strong> #{progress.segment_num}
            <br />{progress.start_sec}s &ndash; {progress.end_sec}s
          </div>
          <div>
            <strong>Time remaining</strong>
            <br /><span className={timeLeft < 120 ? 'warning' : ''}>
              {mins}:{secs.toString().padStart(2, '0')}
            </span>
          </div>
        </div>

        {audioUrl && (
          <audio controls autoPlay key={audioUrl}>
            <source src={audioUrl} type="audio/wav" />
          </audio>
        )}

        <div className="labels">
          <p><strong>Select all labels that apply to this 0.5s clip</strong> (multi-select is expected), then confirm.</p>
          <div className="checkbox-grid">
            {progress.labels.map(label => (
              <label key={label} className={`checkbox-label ${selected.includes(label) ? 'checked' : ''}`}>
                <input
                  type="checkbox"
                  checked={selected.includes(label)}
                  onChange={() => handleToggle(label)}
                />
                {label}
              </label>
            ))}
          </div>
        </div>

        <div className="buttons">
          <button className="primary" onClick={() => onConfirm(selected)}>
            Confirm Labels
          </button>
          <button onClick={onSkip}>Skip</button>
          <button className="danger" onClick={onQuit}>Save &amp; Quit</button>
        </div>
      </div>
    </div>
  )
}

function SummaryPanel({ message, onNew }) {
  return (
    <div className="container">
      <h1>Audio Data Labelling</h1>
      <div className="panel">
        <h2>Done</h2>
        <p>{message}</p>
        <div className="buttons">
          <button className="primary" onClick={onNew}>Start New Session</button>
        </div>
      </div>
    </div>
  )
}
