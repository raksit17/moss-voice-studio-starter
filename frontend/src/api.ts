export interface Voice {
  id: string
  name: string
  language: 'Thai' | 'English'
  created_at: string
  transcript?: string
  character?: string
}

export interface Job {
  id: string
  voice_id: string | null
  model_id?: string | null
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
export interface GenerationSettings { temperature: number; top_p: number; top_k: number }
export const createJob = (text: string, language: string, voiceId: string | null, settings: GenerationSettings, modelId?: string | null) =>
  request<{ id: string; status: string }>('/v1/jobs', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text, language, voice_id: voiceId, model_id: modelId || null, ...settings }),
  })
export const deleteVoice = (id: string) => request<{ deleted: boolean }>(`/v1/voices/${id}`, { method: 'DELETE' })
export const createVoice = (name: string, language: string, file: File, transcript = '', character = '') => {
  const form = new FormData()
  form.append('name', name)
  form.append('language', language)
  form.append('consent', 'true')
  form.append('transcript', transcript)
  form.append('character', character)
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
  settings: GenerationSettings,
): Promise<Response> {
  const response = await fetch(BASE_URL + '/v1/stream', {
    method: 'POST',
    headers: { 'X-API-Key': API_KEY, 'Content-Type': 'application/json' },
    body: JSON.stringify({ text, language, voice_id: voiceId, instructions: instructions || null, ...settings }),
    signal,
  })
  if (!response.ok) {
    const data = await response.json().catch(() => ({}))
    throw new Error(typeof data.detail === 'string' ? data.detail : 'Stream failed: HTTP ' + response.status)
  }
  return response
}

export interface SavedModel {
  id: string
  name: string
  model_path: string
  precision: string
  status: 'ready' | 'pending_validation' | 'failed'
  is_default: number
  created_at: string
}
export interface ModelRuntime {
  state: string
  loaded_model_id: string | null
  device: string
  error: string | null
}
export const getModels = async () => (await request<{items: SavedModel[]}>('/v1/models')).items
export const getModelRuntime = () => request<ModelRuntime>('/v1/models/runtime')
export const importModel = (name: string, model_path: string, precision: string) =>
  request<SavedModel>('/v1/models/import', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({name,model_path,precision}) })
export const activateModel = (id: string) => request<SavedModel>(`/v1/models/${id}/activate`, {method:'POST'})
export const loadModel = (id: string) => request<ModelRuntime>(`/v1/models/${id}/load`, {method:'POST'})
export const unloadModel = (id: string) => request<ModelRuntime>(`/v1/models/${id}/unload`, {method:'POST'})
export const validateModel = (id: string) => request<SavedModel>(`/v1/models/${id}/validate`, {method:'POST'})
