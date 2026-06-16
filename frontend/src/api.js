const BASE = ''

async function req(method, path, body) {
  const opts = {
    method,
    headers: { 'Content-Type': 'application/json' },
  }
  if (body) opts.body = JSON.stringify(body)
  const res = await fetch(`${BASE}${path}`, opts)
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || 'Request failed')
  }
  return res
}

export async function getStatus() {
  const res = await req('GET', '/api/session/status')
  return res.json()
}

export async function startSession(dataDir, labels, windowSize, hopSize) {
  const res = await req('POST', '/api/session/start', {
    data_dir: dataDir,
    labels,
    window_size: windowSize,
    hop_size: hopSize,
  })
  return res.json()
}

export async function resumeSession() {
  const res = await req('POST', '/api/session/resume')
  return res.json()
}

export async function clearSession() {
  await req('POST', '/api/session/clear')
}

export async function getSegmentInfo() {
  const res = await req('GET', '/api/segment/info')
  return res.json()
}

export function getSegmentAudioUrl() {
  return `${BASE}/api/segment/audio`
}

export async function confirmLabels(selectedLabels) {
  const res = await req('POST', '/api/segment/confirm', {
    selected_labels: selectedLabels,
  })
  return res.json()
}

export async function skipSegment() {
  const res = await req('POST', '/api/segment/skip')
  return res.json()
}

export async function saveSession() {
  await req('POST', '/api/session/save')
}
