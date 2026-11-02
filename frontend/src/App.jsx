import { useState, useEffect, useCallback } from 'react'
import * as api from './api'

const MAX_SESSION_SECONDS = 20 * 60

export default function App() {
  const [step, setStep] = useState('loading') // loading | setup | labelling | summary
  const [session, setSession] = useState(null)
  const [hasSavedSession, setHasSavedSession] = useState(false)
  const [progress, setProgress] = useState(null)
  const [audioUrl, setAudioUrl] = useState(null)
  const [message, setMessage] = useState('')
  const [timeLeft, setTimeLeft] = useState(MAX_SESSION_SECONDS)

  // Check for saved session on mount
  useEffect(() => {
    api.getStatus().then((data) => {
      if (data.has_session) {
        setSession(data.session)
        setHasSavedSession(true)
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
    setHasSavedSession(true)
    setStep('setup')
    setAudioUrl(null)
  }, [])

  async function handleStart(dataDir, windowSize, hopSize) {
    try {
      const prog = await api.startSession(dataDir, windowSize, hopSize)
      setProgress(prog)
      setSession({ window_size: windowSize, hop_size: hopSize, session_start_time: Date.now() / 1000 })
      setHasSavedSession(false)
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
        setHasSavedSession(false)
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

  async function handleConfirm(annotations) {
    try {
      const res = await api.confirmLabels(annotations)
      if (res.done) {
        setAudioUrl(null)
        setProgress(null)
        setHasSavedSession(false)
        setMessage(res.message || 'Done')
        setStep('summary')
        return
      }
      setProgress(res)
      setMessage('')
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
      setMessage('')
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
    setHasSavedSession(true)
    setStep('setup')
  }

  if (step === 'loading') {
    return <div className="container"><p>Loading...</p></div>
  }

  if (step === 'setup') {
    return (
      <SetupPanel
        hasSession={hasSavedSession}
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
        message={message}
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
          setHasSavedSession(false)
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
  const [dataDir, setDataDir] = useState('')
  const [windowSize, setWindowSize] = useState(session?.window_size || 1.0)
  const [hopSize, setHopSize] = useState(session?.hop_size || 0.5)

  function handleSubmit(e) {
    e.preventDefault()
    if (!dataDir.trim()) return
    onStart(dataDir.trim(), windowSize, hopSize)
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
              step="0.01"
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

function LabellingPanel({ progress, audioUrl, timeLeft, message, onConfirm, onSkip, onQuit }) {
  const [annotations, setAnnotations] = useState({})

  const mins = Math.floor(timeLeft / 60)
  const secs = Math.floor(timeLeft % 60)

  function handleStateChange(label, state) {
    setAnnotations(prev => ({
      ...prev,
      [label]: {
        state: state ? 1 : 0,
        confidence: state ? prev[label]?.confidence ?? null : null,
      },
    }))
  }

  function handleConfidenceChange(label, confidence) {
    setAnnotations(prev => ({
      ...prev,
      [label]: { ...prev[label], confidence: confidence ? Number(confidence) : null },
    }))
  }

  useEffect(() => {
    setAnnotations(Object.fromEntries(
      progress.labels.map(label => [label, { state: 0, confidence: null }])
    ))
  }, [audioUrl, progress.labels])

  const canConfirm = progress.labels.every(label => {
    const annotation = annotations[label]
    return annotation && (
      annotation.state === 0 || annotation.confidence === 1 || annotation.confidence === 2
    )
  })

  return (
    <div className="container labelling-container">
      <h1>Audio Data Labelling</h1>

      <div className="panel">
        {message && <p className="error">{message}</p>}
        <div className="progress-bar">
          <div className="progress-fill" style={{ width: `${(progress.file_idx / progress.total_files) * 100}%` }} />
        </div>

        <div className="info-grid">
          <div>
            <strong>Recording</strong> {progress.file_idx}/{progress.total_files}
            <br /><code>{progress.recording_id}</code>
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

        {(progress.unreadable_file_count > 0 || progress.short_file_count > 0) && (
          <p className="hint">
            Skipped {progress.unreadable_file_count} unreadable file(s) and
            {' '}{progress.short_file_count} file(s) shorter than one window.
          </p>
        )}

        {audioUrl && (
          <audio controls autoPlay key={audioUrl}>
            <source src={audioUrl} type="audio/wav" />
          </audio>
        )}

        <div className="labels">
          <p><strong>Annotate each label for this segment:</strong></p>
          <p className="hint">
            Tick every label that applies. Choose confidence for each selected label.
            Use “Uncertain” when the window as a whole cannot be labelled reliably.
          </p>
          <div className="label-groups">
            {progress.label_groups.map(group => (
              <section className="label-group" key={group.dimension}>
                <h3>{group.dimension}</h3>
                {group.labels.map(label => {
                  const annotation = annotations[label.key] || { state: 0, confidence: null }
                  return (
                    <div className="annotation-row" key={label.key}>
                      <label className="annotation-checkbox">
                        <input
                          type="checkbox"
                          checked={annotation.state === 1}
                          onChange={event => handleStateChange(label.key, event.target.checked)}
                        />
                        <span>{label.name}</span>
                      </label>
                      {annotation.state === 1 && (
                        <label>
                          Confidence
                          <select
                            value={annotation.confidence ?? ''}
                            onChange={event => handleConfidenceChange(label.key, event.target.value)}
                          >
                            <option value="">Select confidence</option>
                            <option value={2}>High (2)</option>
                            <option value={1}>Moderate (1)</option>
                          </select>
                        </label>
                      )}
                    </div>
                  )
                })}
              </section>
            ))}
          </div>
        </div>

        <div className="buttons">
          <button className="primary" disabled={!canConfirm} onClick={() => onConfirm(annotations)}>
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
