export interface Voice {
  id: string
  name: string
  language: 'Thai' | 'English'
  created_at: string
  transcript?: string
}

export interface Job {
  id: string
  voice_id: string | null
  text: string
  language: string
  status: 'queued' | 'running' | 'completed' | 'failed'
  error: string | null
  audio_url: string | null
  created_at: string
  updated_at: string
}

export interface Health {
  ok: boolean
  engine: 'not_loaded' | 'loading' | 'ready' | 'error'
  device: string
  model: string
  error: string | null
  sample_rate: number
  streaming: boolean
  stream_backend?: string | null
}

export const BASE_URL = import.meta.env.VITE_API_URL ?? 'http://127.0.0.1:8001'
const API_KEY = import.meta.env.VITE_API_KEY ?? 'local-dev-key'

export async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let res: Response
  try {
    res = await fetch(`${BASE_URL}${path}`, {
      ...init,
      headers: { 'X-API-Key': API_KEY, ...(init.headers ?? {}) },
    })
  } catch {
    throw new Error('เชื่อมต่อ Backend ไม่ได้ — ตรวจว่า FastAPI ทำงานที่พอร์ต 8001')
  }
  if (!res.ok) {
    const json = await res.json().catch(() => null)
    const detail = json?.detail
    throw new Error(typeof detail === 'string' ? detail : `API error: ${res.status}`)
  }
  return res.json() as Promise<T>
}

export const getHealth = () => request<Health>('/v1/health')
export interface StreamStatus { configured: boolean; ready: boolean; reason: string | null }
export const getStreamStatus = () => request<StreamStatus>('/v1/stream/status')
export const getVoices = async () => (await request<{ items: Voice[] }>('/v1/voices')).items
export const getJobs = async () => (await request<{ items: Job[] }>('/v1/jobs')).items
export const createJob = (text: string, language: string, voiceId: string | null) =>
  request<{ id: string; status: string }>('/v1/jobs', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text, language, voice_id: voiceId }),
  })
export const deleteVoice = (id: string) => request<{ deleted: boolean }>(`/v1/voices/${id}`, { method: 'DELETE' })
export const createVoice = (name: string, language: string, file: File, transcript = '') => {
  const form = new FormData()
  form.append('name', name)
  form.append('language', language)
  form.append('consent', 'true')
  form.append('transcript', transcript)
  form.append('audio', file)
  return request<Voice>('/v1/voices', { method: 'POST', body: form })
}
export async function getAudio(path: string): Promise<string> {
  const res = await fetch(`${BASE_URL}${path}`, { headers: { 'X-API-Key': API_KEY } })
  if (!res.ok) throw new Error('ไม่สามารถโหลดไฟล์เสียงได้')
  return URL.createObjectURL(await res.blob())
}


/** The response body is progressive raw PCM, not a WAV blob. */
export async function streamSpeech(
  text: string,
  language: 'Thai' | 'English',
  voiceId: string | null,
  instructions: string,
  signal: AbortSignal,
): Promise<Response> {
  const response = await fetch(BASE_URL + '/v1/stream', {
    method: 'POST',
    headers: { 'X-API-Key': API_KEY, 'Content-Type': 'application/json' },
    body: JSON.stringify({ text, language, voice_id: voiceId, instructions: instructions || null }),
    signal,
  })
  if (!response.ok) {
    const data = await response.json().catch(() => ({}))
    throw new Error(typeof data.detail === 'string' ? data.detail : 'Stream failed: HTTP ' + response.status)
  }
  return response
}
