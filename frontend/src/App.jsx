import { useState, useEffect, useCallback, useRef } from 'react'
import * as api from './api'

const MAX_SESSION_SECONDS = 20 * 60

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

  async function handleStart(dataDir, labels, windowSize, hopSize) {
    try {
      const prog = await api.startSession(dataDir, labels, windowSize, hopSize)
      setProgress(prog)
      setSession(prev => ({ ...prev, session_start_time: Date.now() / 1000 }))
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
      setProgress(prog)
      setSession(prev => ({ ...prev, session_start_time: Date.now() / 1000 }))
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
  const [labels, setLabels] = useState(
    session?.labels
      ? session.labels.filter(l => l !== 'noise' && l !== 'silence').join(', ')
      : ''
  )
  const [windowSize, setWindowSize] = useState(session?.window_size || 1.0)
  const [hopSize, setHopSize] = useState(session?.hop_size || 0.5)

  function handleSubmit(e) {
    e.preventDefault()
    if (!dataDir.trim()) return
    onStart(dataDir.trim(), labels, windowSize, hopSize)
  }

  return (
    <div className="container">
      <h1>Audio Data Labelling Tool</h1>
      <form onSubmit={handleSubmit} className="panel">
        <h2>Configuration</h2>

        <label>
          Data Directory
          <input
            type="text"
            value={dataDir}
            onChange={e => setDataDir(e.target.value)}
            placeholder="/path/to/audio/files"
            required
          />
        </label>

        <label>
          Custom Labels (comma-separated)
          <input
            type="text"
            value={labels}
            onChange={e => setLabels(e.target.value)}
            placeholder="belt, breathy, vibrato, straight"
          />
          <span className="hint">'noise' and 'silence' are always included</span>
        </label>

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
          <p><strong>Select labels for this segment:</strong></p>
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
