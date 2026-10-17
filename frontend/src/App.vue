<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import {
  Activity, AudioLines, ArrowDownToLine, ArrowLeftRight, Check,
  ChevronDown, Clock3, CloudOff, Code2, Copy, Cpu, FileAudio,
  FolderOpen, Headphones, Home, Info, KeyRound, Layers3, Library,
  Menu, Mic2, MoreHorizontal, Pause, Play, Plus, RefreshCcw,
  Settings2, ShieldCheck, SlidersHorizontal, Sparkles, Trash2,
  UploadCloud, Volume2, WandSparkles, Waves, X, Zap,
} from 'lucide-vue-next'
import {
  type Health, type Job, type Voice, createJob, createVoice,
  deleteVoice, getAudio, getHealth, getJobs, getVoices,
  getStreamStatus, streamSpeech, type StreamStatus,
  type GenerationSettings, type SavedModel, type ModelRuntime, getModels, getModelRuntime,
  importModel, activateModel, loadModel, unloadModel, validateModel,
  type VoicePackage, getVoicePackages, buildVoicePackage, deleteVoicePackage,
} from './api'
import { playPcmResponse } from './pcm-player'

type Page = 'studio' | 'voices' | 'history' | 'model' | 'api'
const page = ref<Page>('studio')
const sidebarOpen = ref(false)
const health = ref<Health | null>(null)
const online = ref(false)
const voices = ref<Voice[]>([])
const savedModels = ref<SavedModel[]>([])
const voicePackages = ref<VoicePackage[]>([])
const selectedVoicePackage = ref('')
const builderType = ref<'voice' | 'generation'>('generation')
const builderSourceId = ref('')
const builderName = ref('test1-small')
const packageBusy = ref(false)
const modelRuntime = ref<ModelRuntime | null>(null)
const selectedModel = ref('')
const importName = ref('')
const importPath = ref('')
const importPrecision = ref('bf16')
const modelBusy = ref(false)
const jobs = ref<Job[]>([])
const selectedVoice = ref('')
const language = ref<'Thai' | 'English'>('Thai')
const temperature = ref(1.7)
const topP = ref(0.8)
const topK = ref(25)
const text = ref('กลับมาแล้วเหรอคะ... ฉันกำลังรอคุณอยู่พอดีเลย วันนี้มีอะไรอยากเล่าให้ฟังไหมคะ?')
const notification = ref('')
const error = ref('')
const creating = ref(false)
const activeJobId = ref<string | null>(null)
const clockNow = ref(Date.now())
const playerUrl = ref<string | null>(null)
const player = ref<HTMLAudioElement | null>(null)
const playing = ref(false)
const uploadOpen = ref(false)
const uploadName = ref('')
const uploadCharacter = ref('')
const uploadLanguage = ref<'Thai' | 'English'>('Thai')
const uploadFile = ref<File | null>(null)
const uploadConsent = ref(false)
const uploadTranscript = ref('')
const liveActive = ref(false)
const liveBytes = ref(0)
const liveInstructions = ref('')
const liveStatus = ref<StreamStatus | null>(null)
let liveAbort: AbortController | null = null
let liveContext: AudioContext | null = null
const uploading = ref(false)
const pickedFileInput = ref<HTMLInputElement | null>(null)
let timer: ReturnType<typeof setInterval> | null = null
let clockTicker: ReturnType<typeof setInterval> | null = null
let toastTimer: ReturnType<typeof setTimeout> | null = null
const examples = [
  { name: 'อบอุ่น', text: 'กลับมาแล้วเหรอคะ... ฉันกำลังรอคุณอยู่พอดีเลย วันนี้มีอะไรอยากเล่าให้ฟังไหมคะ?' },
  { name: 'ตื่นเต้น', text: 'ว้าว! จริงเหรอคะ? ดีใจด้วยมาก ๆ เลย ฉันอยากฟังรายละเอียดทั้งหมดเลยค่ะ!' },
  { name: 'อ่อนโยน', text: 'วันนี้เหนื่อยมามากแล้วสินะคะ ไม่เป็นไรนะ พักสักหน่อยก็ได้ค่ะ' },
  { name: 'ไทย + อังกฤษ', text: 'วันนี้ฉันจะ Deploy NestJS API แล้วลองเชื่อม PostgreSQL ผ่าน Docker ค่ะ' },
]
const currentJob = computed(() => jobs.value.find(j => j.id === activeJobId.value) ?? null)
const finishedCount = computed(() => jobs.value.filter(j => j.status === 'completed').length)
const isBusy = computed(() => !!currentJob.value && ['queued', 'running'].includes(currentJob.value.status))
const selectedVoiceName = computed(() => selectedVoicePackage.value
  ? voicePackages.value.find(p => p.id === selectedVoicePackage.value)?.name ?? 'Saved F5 voice'
  : voices.value.find(v => v.id === selectedVoice.value)?.name ?? 'Default voice')
const packageSources = computed(() => builderType.value === 'voice'
  ? voices.value.filter(v => v.language === 'Thai' && !!v.transcript?.trim())
      .map(v => ({ id: v.id, label: v.name + ' · ' + v.transcript?.slice(0, 60) }))
  : jobs.value.filter(j => j.status === 'completed' && j.language === 'Thai')
      .map(j => ({ id: j.id, label: j.text.slice(0, 80) + ' · ' + dateLabel(j.created_at) })))
const latestJobs = computed(() => jobs.value.slice(0, 5))
const historyJobs = computed(() => jobs.value)
const dateLabel = (str: string) => new Date(str).toLocaleString('th-TH', { dateStyle: 'medium', timeStyle: 'short' })
// The live clock is client-side; completed duration is measured by the backend worker.
function jobSeconds(job: Job): number | null {
  if (job.status === 'queued') {
    const queuedAt = Date.parse(job.created_at)
    return Number.isFinite(queuedAt) ? Math.max(0, Math.floor((clockNow.value - queuedAt) / 1000)) : null
  }
  if (job.status === 'running') {
    const runningAt = Date.parse(job.started_at || job.created_at)
    return Number.isFinite(runningAt) ? Math.max(0, Math.floor((clockNow.value - runningAt) / 1000)) : null
  }
  if (typeof job.duration_seconds === 'number' && Number.isFinite(job.duration_seconds)) {
    return Math.max(0, Math.round(job.duration_seconds))
  }
  if (job.started_at && job.finished_at) {
    const difference = Date.parse(job.finished_at) - Date.parse(job.started_at)
    return Number.isFinite(difference) ? Math.max(0, Math.round(difference / 1000)) : null
  }
  return null // Legacy jobs without a measured duration must not display an invented timing.
}
function displayDuration(seconds: number | null): string {
  if (seconds === null) return '—'
  const total = Math.floor(seconds)
  const pad = (n: number) => String(n).padStart(2, '0')
  const minutes = Math.floor(total / 60)
  return minutes >= 60
    ? `${pad(Math.floor(minutes / 60))}:${pad(minutes % 60)}:${pad(total % 60)}`
    : `${pad(minutes)}:${pad(total % 60)}`
}
function jobTimeTitle(job: Job): string {
  if (job.status === 'queued') return 'เวลาที่รอในคิว'
  if (job.status === 'running') return job.started_at ? 'เวลาที่ใช้สร้างเสียง' : 'เวลาตั้งแต่ส่งงาน'
  return job.status === 'completed' ? 'เวลาสร้างเสียงทั้งหมด' : 'เวลาก่อนเกิดข้อผิดพลาด'
}
function audioFilename(job: Job): string {
  return `voice-${job.id.slice(0, 8)}.wav`
}

function alertMessage(message: string, type: 'notice' | 'error' = 'notice') {
  if (toastTimer) clearTimeout(toastTimer)
  notification.value = type === 'notice' ? message : ''
  error.value = type === 'error' ? message : ''
  toastTimer = setTimeout(() => { notification.value = ''; error.value = '' }, 6000)
}
function navigate(next: Page) {
  page.value = next
  sidebarOpen.value = false
}
async function refresh() {
  try {
    const [h, vs, js, st, ms, rt, vp] = await Promise.all([getHealth(), getVoices(), getJobs(), getStreamStatus(), getModels(), getModelRuntime(), getVoicePackages()])
    voicePackages.value = vp
    if (selectedVoicePackage.value && !vp.some(p => p.id === selectedVoicePackage.value)) selectedVoicePackage.value = ''
    savedModels.value = ms
    modelRuntime.value = rt
    if (!selectedModel.value || !ms.some(m => m.id === selectedModel.value)) selectedModel.value = ms.find(m => m.is_default)?.id || ''
    liveStatus.value = st
    health.value = h
    voices.value = vs
    jobs.value = js
    online.value = true
  } catch {
    online.value = false
    health.value = null
  }
}
async function generate() {
  if (!text.value.trim()) return alertMessage('กรุณาพิมพ์ข้อความก่อนสร้างเสียง', 'error')
  creating.value = true
  try {
    if (selectedVoicePackage.value && language.value !== 'Thai') throw new Error('F5-TTS-THAI Voice Package รองรับเสียงภาษาไทยในเวอร์ชันนี้')
    const job = await createJob(text.value.trim(), language.value,
      selectedVoicePackage.value ? null : selectedVoice.value || null,
      generationSettings(), selectedVoicePackage.value ? null : selectedModel.value,
      selectedVoicePackage.value || null)
    activeJobId.value = job.id
    alertMessage('ส่งงานเข้า Voice Engine แล้ว — ดูสถานะได้ในรายการด้านล่าง')
    await refresh()
  } catch (e) {
    alertMessage((e as Error).message, 'error')
  } finally {
    creating.value = false
  }
}
async function modelAction(action: 'load' | 'unload' | 'activate' | 'validate' | 'import') {
  modelBusy.value = true
  try {
    if (action === 'import') {
      const added = await importModel(importName.value, importPath.value, importPrecision.value)
      selectedModel.value = added.id
      importName.value = ''; importPath.value = ''
    } else {
      if (!selectedModel.value) throw new Error('Select a saved model')
      if (action === 'load') await loadModel(selectedModel.value)
      if (action === 'unload') await unloadModel(selectedModel.value)
      if (action === 'activate') await activateModel(selectedModel.value)
      if (action === 'validate') await validateModel(selectedModel.value)
    }
    await refresh()
    alertMessage('Model operation completed')
  } catch(e) { alertMessage((e as Error).message, 'error') }
  finally { modelBusy.value = false }
}
async function saveVoicePackage() {
  if (!builderSourceId.value || !builderName.value.trim()) return alertMessage('เลือกต้นฉบับและชื่อ package ก่อนบันทึก', 'error')
  packageBusy.value = true
  try {
    const created = await buildVoicePackage(builderName.value.trim(), builderType.value, builderSourceId.value)
    await refresh()
    selectedVoicePackage.value = created.id
    language.value = 'Thai'
    alertMessage('บันทึก package แล้ว · ใช้ F5 ได้โดยไม่ต้องโหลด MOSS')
  } catch (e) { alertMessage((e as Error).message, 'error') }
  finally { packageBusy.value = false }
}
function useVoicePackage(id: string) {
  selectedVoicePackage.value = id
  language.value = 'Thai'
  navigate('studio')
}
async function removeVoicePackage(pkg: VoicePackage) {
  if (!confirm('ลบ package ' + pkg.name + ' และไฟล์เสียงอ้างอิงที่เก็บไว้ใช่ไหม?')) return
  packageBusy.value = true
  try {
    await deleteVoicePackage(pkg.id)
    if (selectedVoicePackage.value === pkg.id) selectedVoicePackage.value = ''
    await refresh()
    alertMessage('ลบ Voice Package แล้ว')
  } catch (e) { alertMessage((e as Error).message, 'error') }
  finally { packageBusy.value = false }
}
function generationSettings(): GenerationSettings {
  return { temperature: temperature.value, top_p: topP.value, top_k: topK.value }
}
async function playAudio(path: string | null) {
  if (!path) return
  try {
    if (playerUrl.value) URL.revokeObjectURL(playerUrl.value)
    playerUrl.value = await getAudio(path)
    playing.value = false
    await new Promise(resolve => setTimeout(resolve, 50))
    await player.value?.play()
  } catch (e) {
    alertMessage((e as Error).message, 'error')
  }
}
async function downloadAudio(path: string | null, filename: string) {
  if (!path) return
  try {
    const url = await getAudio(path)
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    a.style.display = 'none'
    document.body.appendChild(a)
    a.click()
    a.remove()
    alertMessage('เริ่มดาวน์โหลด ' + filename + ' แล้ว · ตรวจสอบรายการดาวน์โหลดของเบราว์เซอร์')
    setTimeout(() => URL.revokeObjectURL(url), 10000)
  } catch (e) { alertMessage((e as Error).message, 'error') }
}
async function uploadVoice() {
  if (!uploadFile.value || !uploadName.value.trim() || !uploadConsent.value) {
    return alertMessage('กรุณาระบุชื่อ เลือกไฟล์ WAV และยืนยันสิทธิ์ของเสียง', 'error')
  }
  uploading.value = true
  try {
    const voice = await createVoice(uploadName.value, uploadLanguage.value, uploadFile.value, uploadTranscript.value, uploadCharacter.value)
    uploadOpen.value = false
    uploadName.value = ''; uploadFile.value = null; uploadConsent.value = false; uploadTranscript.value = ''; uploadCharacter.value = ''
    selectedVoice.value = voice.id
    await refresh()
    alertMessage(`เพิ่มเสียง ${voice.name} ใน Voice Library แล้ว`)
  } catch (e) { alertMessage((e as Error).message, 'error') }
  finally { uploading.value = false }
}
async function removeVoice(v: Voice) {
  if (!confirm(`ลบเสียงต้นแบบ “${v.name}” ใช่ไหม?`)) return
  try {
    await deleteVoice(v.id)
    if (selectedVoice.value === v.id) selectedVoice.value = ''
    await refresh()
    alertMessage('ลบเสียงต้นแบบเรียบร้อย')
  } catch (e) { alertMessage((e as Error).message, 'error') }
}
function fileChange(event: Event) {
  uploadFile.value = (event.target as HTMLInputElement).files?.[0] ?? null
}
async function copy(textToCopy: string) {
  try { await navigator.clipboard.writeText(textToCopy); alertMessage('คัดลอกเรียบร้อย') }
  catch { alertMessage('คัดลอกไม่สำเร็จ', 'error') }
}
async function liveSpeak() {
  if (!text.value.trim() || liveActive.value) return
  if (!liveStatus.value?.ready) {
    alertMessage('ต้องเปิด SGLang-Omni และตั้งค่า SGLANG_BASE_URL ก่อน', 'error')
    return
  }
  liveAbort = new AbortController()
  liveActive.value = true
  liveBytes.value = 0
  const ctx = new AudioContext()
  liveContext = ctx
  try {
    // Resume on the button gesture to satisfy browser autoplay permissions.
    await ctx.resume()
    const response = await streamSpeech(text.value.trim(), language.value,
      selectedVoice.value || null, liveInstructions.value, liveAbort.signal, generationSettings())
    await playPcmResponse(response, ctx, liveAbort.signal, bytes => {
      liveBytes.value += bytes
    })
    alertMessage('สตรีมเสียงเสร็จแล้ว')
  } catch (e) {
    if (!(e instanceof DOMException && e.name === 'AbortError'))
      alertMessage((e as Error).message, 'error')
  } finally {
    await ctx.close().catch(() => undefined)
    if (liveContext === ctx) liveContext = null
    liveAbort = null
    liveActive.value = false
  }
}
function stopLive() {
  liveAbort?.abort()
  void liveContext?.close().catch(() => undefined)
}
onMounted(async () => {
  await refresh()
  timer = setInterval(() => void refresh(), 3500)
  clockTicker = setInterval(() => { clockNow.value = Date.now() }, 1000)
})
onUnmounted(() => {
  stopLive()
  if (timer) clearInterval(timer)
  if (clockTicker) clearInterval(clockTicker)
  if (toastTimer) clearTimeout(toastTimer)
  if (playerUrl.value) URL.revokeObjectURL(playerUrl.value)
})
</script>

<template>
  <div class="layout">
    <div v-if="sidebarOpen" class="mobile-scrim" @click="sidebarOpen = false"></div>
    <aside class="sidebar" :class="{ shown: sidebarOpen }">
      <div class="brand">
        <div class="brand-mark"><AudioLines :size="23" :stroke-width="2.5" /></div>
        <div class="brand-text"><strong>MOSS<span>VOICE</span></strong><small>CREATIVE STUDIO</small></div>
      </div>

      <div class="sidebar-label">WORKSPACE</div>
      <nav class="sidebar-menu">
        <button :class="{ active: page === 'studio' }" @click="navigate('studio')"><WandSparkles :size="18"/> Voice Playground <span class="nav-active-dot" v-if="page === 'studio'"></span></button>
        <button :class="{ active: page === 'voices' }" @click="navigate('voices')"><Library :size="18"/> Voice Library <span class="nav-count">{{ voices.length }}</span></button>
        <button :class="{ active: page === 'history' }" @click="navigate('history')"><Clock3 :size="18"/> Generation History</button>
      </nav>
      <div class="sidebar-label second">SYSTEM</div>
      <nav class="sidebar-menu">
        <button :class="{ active: page === 'model' }" @click="navigate('model')"><Cpu :size="18"/> Model Manager</button>
        <button :class="{ active: page === 'api' }" @click="navigate('api')"><Code2 :size="18"/> API & Integration</button>
      </nav>
      <div class="sidebar-bottom">
        <div class="system-health">
          <span class="health-orb" :class="{ healthy: online }"></span>
          <div><strong>{{ online ? 'API Connected' : 'API Offline' }}</strong><small>{{ online ? 'Local workspace is active' : 'Start FastAPI backend' }}</small></div>
          <RefreshCcw :size="15" class="refresh-icon" @click="refresh"/>
        </div>
        <div class="sidebar-footer">MOSS-TTS Local Transformer <span>v1.5</span></div>
      </div>
    </aside>

    <main class="main">
      <header class="topbar">
        <div class="topbar-left">
          <button class="mobile-toggle icon-button" @click="sidebarOpen = !sidebarOpen"><Menu :size="21"/></button>
          <div class="breadcrumbs"><span>Workspace</span><span class="breadcrumb-sep">/</span><strong>{{ { studio: 'Voice Playground', voices: 'Voice Library', history: 'Generation History', model: 'Model Manager', api: 'API & Integration' }[page] }}</strong></div>
        </div>
        <div class="top-actions"><div class="model-badge"><span class="mini-dot"></span>MOSS Local v1.5</div><button class="icon-button refresh-button" title="Refresh" @click="refresh"><RefreshCcw :size="17"/></button><div class="avatar">MS</div></div>
      </header>
      <div class="content">
        <div v-if="notification" class="toast success-toast"><Check :size="16"/>{{ notification }} <X :size="14" class="toast-close" @click="notification=''"/></div>
        <div v-if="error" class="toast error-toast"><Info :size="16"/>{{ error }} <X :size="14" class="toast-close" @click="error=''"/></div>

        <template v-if="page === 'studio'">
          <div class="page-header"><div><div class="eyebrow"><Sparkles :size="14"/> VOICE GENERATION</div><h1>Bring your words <em>to life.</em></h1><p>สร้างเสียง AI ภาษาไทยและอังกฤษ พร้อม Voice Cloning บนเครื่องของคุณ</p></div><div class="header-actions"><button class="button ghost" @click="navigate('history')"><Clock3 :size="16"/> History</button><button class="button secondary" @click="uploadOpen = true"><Plus :size="17"/> Add Voice</button></div></div>

          <div class="stat-grid">
            <div class="stat-card"><div class="stat-icon purple"><Waves :size="19"/></div><div><small>Voice Profiles</small><strong>{{ voices.length }}</strong><span>Saved references</span></div></div>
            <div class="stat-card"><div class="stat-icon mint"><Headphones :size="19"/></div><div><small>Generated Clips</small><strong>{{ finishedCount }}</strong><span>Audio generations</span></div></div>
            <div class="stat-card"><div class="stat-icon blue"><Cpu :size="19"/></div><div><small>Voice Engine</small><strong class="small-stat">{{ health?.engine === 'ready' ? 'Ready' : health?.engine === 'loading' ? 'Loading' : online ? 'Standby' : 'Offline' }}</strong><span>{{ health?.device || 'Not connected' }}</span></div></div>
          </div>

          <section class="panel details-panel" style="margin-bottom:18px">
            <label class="modal-label">Speech runtime</label>
            <select class="modal-input" v-model="selectedVoicePackage">
              <option value="">MOSS-TTS v1.5 (Original / imported)</option>
              <option v-for="p in voicePackages" :key="p.id" :value="p.id">{{ p.name }} — F5-TTS-THAI · Reusable Voice Package</option>
            </select>
            <label v-if="!selectedVoicePackage" class="modal-label">MOSS Generation Model</label>
            <select v-if="!selectedVoicePackage" class="modal-input" v-model="selectedModel"><option v-for="m in savedModels.filter(x=>x.status==='ready')" :key="m.id" :value="m.id">{{ m.name }} ({{ m.precision.toUpperCase() }})</option></select>
            <p class="section-desc">{{ selectedVoicePackage
              ? 'Independent F5 Thai runtime · MOSS unloads automatically · package is reference audio, not a trained checkpoint.'
              : 'MOSS checkpoint selection for this job. Switch to a saved package to avoid loading MOSS.' }}</p>
          </section>
          <div class="studio-grid">
            <section class="panel editor-panel">
              <div class="panel-heading"><div><span class="panel-kicker">01 / CREATE</span><h2><WandSparkles :size="19" class="heading-icon"/> Text to Speech</h2><p>พิมพ์ข้อความที่คุณต้องการให้ AI พูด</p></div><div class="pill"><span class="pill-dot"></span> Local Inference</div></div>
              <div class="field-label">Language <span>Choose output language</span></div>
              <div class="language-tabs"><button :class="{ selected: language === 'Thai' }" @click="language = 'Thai'">🇹🇭 <span>Thai</span></button><button :class="{ selected: language === 'English' }" @click="language = 'English'">🇺🇸 <span>English</span></button></div>
              <div class="field-label field-label-space">Your text <span>Up to 600 characters</span></div>
              <div class="text-editor"><textarea v-model="text" maxlength="600" spellcheck="false" placeholder="พิมพ์ข้อความที่ต้องการสร้างเสียงที่นี่..."></textarea><div class="editor-bottom"><span><Sparkles :size="13"/> Supports Thai / English</span><span>{{ text.length }} / 600</span></div></div>
              <div class="field-label field-label-space">Quick prompts <span>Click to try</span></div>
              <div class="prompt-row"><button v-for="prompt in examples" :key="prompt.name" @click="text=prompt.text">{{ prompt.name }}</button></div>
              <div class="editor-divider"></div>
              <div class="stream-params"><label for="live-style">Streaming style hint (optional)</label><input id="live-style" v-model="liveInstructions" maxlength="240" placeholder="e.g. warm, gentle, cheerful" /><span>{{ liveStatus?.ready ? "● SGLang ready · progressive PCM 48 kHz mono" : "○ Streaming requires SGLang-Omni server" }}</span></div><div class="action-row"><div class="quality-mark"><ShieldCheck :size="17"/><div><strong>{{ selectedVoicePackage ? '24 kHz · WAV (F5)' : '48 kHz · Stereo WAV' }}</strong><span>High fidelity audio output</span></div></div><button class="button primary generate-btn" :disabled="creating || isBusy || !text.trim()" @click="generate"><Waves v-if="!creating && !isBusy" :size="18"/><RefreshCcw v-else :size="18" class="spin"/>{{ creating || isBusy ? 'Generating...' : 'Generate Speech' }}</button></div>
              <div class="stream-actions">
                <button v-if="!liveActive" class="button secondary" :disabled="!text.trim() || !liveStatus?.ready || !!selectedVoicePackage" @click="liveSpeak">
                  <Zap :size="17"/> Stream Speech (Live)
                </button>
                <button v-else class="button secondary" @click="stopLive">
                  <Pause :size="17"/> Stop live audio
                </button>
                <span class="stream-progress">{{ liveActive ? 'Playing progressive PCM · ' + Math.round(liveBytes / 1024) + ' KB received' : 'WAV mode remains available offline from SGLang' }}</span>
              </div>
            </section>

            <section class="panel voice-panel">
              <div class="panel-heading"><div><span class="panel-kicker">02 / VOICE IDENTITY</span><h2><Mic2 :size="19" class="heading-icon"/> Choose a Voice</h2><p>เลือกเสียงต้นแบบของตัวละคร</p></div></div>
              <div class="voice-selection"><div class="voice-avatar"><AudioLines :size="24"/></div><div class="voice-select-text"><strong>{{ selectedVoiceName }}</strong><span>{{ selectedVoicePackage ? 'Saved F5 reference package · zero-shot' : selectedVoice ? 'MOSS zero-shot voice cloning' : 'No reference voice' }}</span></div><ChevronDown :size="18" class="select-chevron"/><select v-model="selectedVoice" :disabled="!!selectedVoicePackage"><option value="">Default voice</option><option v-for="voice in voices" :key="voice.id" :value="voice.id">{{ voice.name }}</option></select></div>
              <div class="upload-card" @click="uploadOpen = true"><div class="upload-icon"><UploadCloud :size="25"/></div><strong>Add your own voice</strong><span>อัปโหลดเสียง WAV ที่ได้รับอนุญาต เพื่อใช้สร้างเสียงพูดใหม่ด้วยบุคลิกเสียงเดิม</span><button class="upload-link">Upload reference audio <span>↗</span></button></div>
              <div v-if="!selectedVoicePackage" class="settings-section"><h3><SlidersHorizontal :size="16"/> Model parameters</h3><label class="setting-control"><span>Temperature</span><input v-model.number="temperature" type="number" min="0.1" max="2" step="0.1"/></label><label class="setting-control"><span>Top P</span><input v-model.number="topP" type="number" min="0.05" max="1" step="0.05"/></label><label class="setting-control"><span>Top K</span><input v-model.number="topK" type="number" min="1" max="100" step="1"/></label><div class="info-setting"><span>Voice method</span><strong>Zero-shot</strong></div><p class="settings-note"><Info :size="14"/> ค่าเริ่มต้นอิงตามคำแนะนำของ MOSS; ปรับได้ต่อการสร้าง</p></div>
            </section>
          </div>

          <section class="panel results-panel">
            <div class="results-heading">
              <div><div class="panel-kicker">03 / OUTPUT</div><h2><Volume2 :size="20" class="heading-icon"/> Audio Preview & Download</h2></div>
              <span v-if="currentJob" class="status-tag" :class="currentJob.status">{{ currentJob.status }}</span>
              <span v-else class="waiting-tag">Waiting for generation</span>
            </div>
            <div v-if="currentJob" class="generation-timer" role="timer" aria-label="Generation elapsed time">
              <div class="generation-timer-caption">
                <Clock3 :size="19"/>
                <div>
                  <strong>{{ jobTimeTitle(currentJob) }}</strong>
                  <span>{{ currentJob.status === 'queued' ? 'ยังไม่เริ่มประมวลผล' : currentJob.status === 'running' ? 'จับเวลาจริงขณะประมวลผล · อัปเดตทุกวินาที' : 'เวลาประมวลผลจาก Backend · ไม่รวมเวลารอในคิว' }}</span>
                </div>
              </div>
              <strong class="generation-clock">{{ displayDuration(jobSeconds(currentJob)) }}</strong>
              <span class="generation-clock-unit">นาที:วินาที</span>
            </div>
            <template v-if="currentJob && currentJob.status === 'completed'">
              <div class="audio-result">
                <div class="audio-result-icon"><FileAudio :size="22"/></div>
                <div class="audio-info">
                  <strong>สร้างเสียงสำเร็จ</strong>
                  <span>{{ currentJob.language }} · WAV · {{ dateLabel(currentJob.created_at) }}</span>
                </div>
                <button class="button ghost" @click="playAudio(currentJob.audio_url)"><Play :size="15"/> ฟังเสียง</button>
              </div>
              <div class="download-panel">
                <div class="download-panel-label"><ArrowDownToLine :size="20"/><strong>ดาวน์โหลดไฟล์เสียง</strong></div>
                <div class="download-panel-meta">
                  <strong>{{ audioFilename(currentJob) }}</strong>
                  <span>WAV · บันทึกลงตำแหน่งดาวน์โหลดที่ตั้งค่าไว้ในเบราว์เซอร์ (โดยทั่วไปคือ Downloads)</span>
                </div>
                <button class="button primary" :disabled="!currentJob.audio_url" @click="downloadAudio(currentJob.audio_url, audioFilename(currentJob))">
                  <ArrowDownToLine :size="18"/> ดาวน์โหลด WAV
                </button>
              </div>
            </template>
            <template v-else-if="currentJob && currentJob.status === 'failed'">
              <div class="empty-result failed-result"><Info :size="28"/><strong>Generation failed</strong><span>{{ currentJob.error }}</span></div>
            </template>
            <template v-else-if="currentJob">
              <div class="empty-result">
                <div class="pulse-wave"><span></span><span></span><span></span><span></span><span></span></div>
                <strong>{{ currentJob.status === 'queued' ? 'รอคิวสร้างเสียง' : 'กำลังสร้างเสียง' }}</strong>
                <span>ระบบกำลังประมวลผล · เมื่อสำเร็จจะมีปุ่มดาวน์โหลด WAV แสดงด้านล่าง</span>
              </div>
            </template>
            <template v-else>
              <div class="empty-result"><div class="empty-wave"><AudioLines :size="30"/></div><strong>Your voice is waiting to be created</strong><span>เลือกเสียง พิมพ์ข้อความ แล้วกด Generate Speech เพื่อเริ่มต้น</span></div>
            </template>
            <audio v-if="playerUrl" ref="player" :src="playerUrl" controls class="html-player" @play="playing=true" @pause="playing=false" @ended="playing=false"></audio>
          </section>
        </template>

        <template v-if="page === 'voices'"><div class="page-header"><div><div class="eyebrow"><Library :size="14"/> YOUR LIBRARY</div><h1>Voice <em>Library.</em></h1><p>จัดการเสียงต้นแบบสำหรับ Zero-shot Voice Cloning และใช้ Voice ID กับแอปอื่น</p></div><button class="button primary" @click="uploadOpen = true"><Plus :size="17"/> Add a voice</button></div><div class="panel library-panel"><div class="results-heading"><div><h2><Mic2 :size="20" class="heading-icon"/> Saved profiles</h2><p>{{ voices.length }} voices available</p></div></div><div v-if="voices.length" class="voice-list"><div v-for="voice in voices" :key="voice.id" class="voice-item"><div class="voice-item-icon"><AudioLines :size="21"/></div><div class="voice-item-info"><strong>{{ voice.name }}<small v-if="voice.character" class="character-tag">{{ voice.character }}</small></strong><span>{{ voice.language }} · {{ dateLabel(voice.created_at) }} · {{ voice.id.slice(0,8) }}</span></div><div class="voice-item-actions"><button class="small-button" @click="selectedVoice=voice.id; navigate('studio')"><WandSparkles :size="15"/> Use voice</button><button class="icon-button danger-icon" title="Delete voice" @click="removeVoice(voice)"><Trash2 :size="17"/></button></div></div></div><div v-else class="empty-result tall"><div class="empty-wave"><Mic2 :size="29"/></div><strong>No voices saved yet</strong><span>เพิ่มไฟล์เสียง WAV ที่มีสิทธิ์ใช้งาน เพื่อโคลนเสียงของตัวละคร</span><button class="button secondary" @click="uploadOpen=true"><UploadCloud :size="16"/> Upload reference</button></div></div></template>

        <template v-if="page === 'history'"><div class="page-header"><div><div class="eyebrow"><Clock3 :size="14"/> AUDIO OUTPUTS</div><h1>Generation <em>History.</em></h1><p>ตรวจสถานะงานย้อนหลัง เล่น และดาวน์โหลดไฟล์เสียงที่สร้างไว้</p></div><button class="button secondary" @click="refresh"><RefreshCcw :size="16"/> Refresh</button></div><div class="panel library-panel"><div class="results-heading"><h2><Headphones :size="20" class="heading-icon"/> Recent jobs</h2><span class="waiting-tag">{{ historyJobs.length }} records</span></div><div v-if="historyJobs.length" class="job-list"><div v-for="job in historyJobs" :key="job.id" class="job-item"><div class="job-icon"><FileAudio :size="20"/></div><div class="job-info"><strong>{{ job.text }}</strong><span>{{ job.language }} · {{ dateLabel(job.created_at) }} · {{ jobTimeTitle(job) }}: {{ displayDuration(jobSeconds(job)) }}</span><small v-if="job.error" class="error-text">{{ job.error }}</small></div><span class="status-tag" :class="job.status">{{ job.status }}</span><button class="icon-button" :disabled="job.status !== 'completed'" @click="playAudio(job.audio_url)" title="Play"><Play :size="16"/></button><button class="button secondary history-download" :disabled="job.status !== 'completed'" @click="downloadAudio(job.audio_url, audioFilename(job))" title="Download WAV"><ArrowDownToLine :size="16"/> WAV</button></div></div><div v-else class="empty-result tall"><div class="empty-wave"><Clock3 :size="29"/></div><strong>No generations yet</strong><span>สร้างเสียงจากหน้า Playground แล้วผลลัพธ์จะอยู่ที่นี่</span><button class="button secondary" @click="navigate('studio')">Open Playground</button></div></div></template>

        <template v-if="page === 'model'">
          <section class="panel details-panel" style="margin-bottom:18px">
            <div class="eyebrow"><WandSparkles :size="14"/> VOICE MODEL BUILDER</div>
            <h2>Create Small Voice Package</h2>
            <p class="section-desc">สร้างเสียงจาก MOSS ครั้งแรก แล้วบันทึก WAV + Transcript เป็น package ของ F5-TTS-THAI โดยไม่ต้องเปิด MOSS สำหรับข้อความใหม่ (ไม่ใช่โมเดลที่ฝึกแล้ว)</p>
            <label class="modal-label">Source type</label>
            <select v-model="builderType" class="modal-input" @change="builderSourceId=''">
              <option value="generation">Completed MOSS Generation (recommended)</option>
              <option value="voice">Uploaded Voice Profile with transcript</option>
            </select>
            <label class="modal-label">Source voice / completed Thai generation</label>
            <select class="modal-input" v-model="builderSourceId">
              <option value="">Choose source WAV...</option>
              <option v-for="source in packageSources" :key="source.id" :value="source.id">{{ source.label }}</option>
            </select>
            <p v-if="!packageSources.length" class="section-desc">ไม่พบเสียงต้นฉบับภาษาไทยที่พร้อมใช้งาน · สร้างเสียง MOSS ให้เสร็จหรืออัปโหลด WAV พร้อม transcript</p>
            <label class="modal-label">Saved model name</label>
            <input v-model="builderName" class="modal-input" maxlength="80" placeholder="test1-small"/>
            <button class="button primary" style="margin-top:14px" :disabled="packageBusy || !builderName.trim() || !builderSourceId" @click="saveVoicePackage">Save Reusable Voice Package</button>
            <p class="section-desc">F5 uses a separate Python worker. Original WAV around 2–8 seconds gives better results; some MOSS generations may be too long for ideal cloning.</p>
            <h2 style="margin-top:25px">Saved Voice Packages ({{ voicePackages.length }})</h2>
            <div v-for="p in voicePackages" :key="p.id" class="voice-item" style="margin-top:10px">
              <div class="voice-item-icon"><Mic2 :size="19"/></div>
              <div class="voice-item-info">
                <strong>{{ p.name }}</strong>
                <span>F5-TTS-THAI · {{ p.method }} · {{ p.source_type }} · {{ dateLabel(p.created_at) }}</span>
                <small class="wrap-text">{{ p.package_dir }}</small>
              </div>
              <div class="voice-item-actions">
                <button class="small-button" @click="useVoicePackage(p.id)">Use in Playground</button>
                <button class="icon-button danger-icon" title="Delete saved voice package" :disabled="packageBusy" @click="removeVoicePackage(p)"><Trash2 :size="16"/></button>
              </div>
            </div>
            <p v-if="!voicePackages.length" class="section-desc">No small voice packages saved yet.</p>
          </section>
          <div class="page-header"><div><div class="eyebrow"><Cpu :size="14"/> MODEL LIBRARY</div><h1>Saved <em>Models.</em></h1><p>Import a local checkpoint, validate it and choose which model generates speech.</p></div><button class="button secondary" @click="refresh"><RefreshCcw :size="16"/> Refresh</button></div>
          <section class="panel details-panel">
            <h2>Registered Models ({{ savedModels.length }})</h2>
            <div v-for="m in savedModels" :key="m.id" class="voice-item" style="margin-top:12px">
              <input type="radio" v-model="selectedModel" :value="m.id" :aria-label="m.name"/>
              <div class="voice-item-info"><strong>{{ m.name }}</strong><span>{{ m.precision.toUpperCase() }} · {{ m.status }} · {{ m.is_default ? 'Default' : 'Saved' }} · {{ modelRuntime?.loaded_model_id === m.id ? 'GPU loaded' : 'Not loaded' }}</span><small class="wrap-text">{{ m.model_path }}</small></div>
            </div>
            <p v-if="!savedModels.length">No models registered.</p>
            <div class="modal-actions">
              <button class="button primary" :disabled="modelBusy || !selectedModel" @click="modelAction('load')">Load Model</button>
              <button class="button secondary" :disabled="modelBusy || !selectedModel" @click="modelAction('unload')">Unload</button>
              <button class="button secondary" :disabled="modelBusy || !selectedModel" @click="modelAction('activate')">Set Default</button>
              <button class="button secondary" :disabled="modelBusy || !selectedModel" @click="modelAction('validate')">Validate WAV</button>
            </div>
            <p class="section-desc">GPU: {{ modelRuntime?.device || 'Not loaded' }} · Runtime: {{ modelRuntime?.state || 'Unknown' }}. Only one model is resident at a time.</p>
            <div class="model-note"><Info :size="18"/><div><strong>INT8 Safety</strong><p>INT8 export and checkpoint reload are disabled until architecture-specific compatibility is verified. A saved INT8 folder will require validation before activation.</p></div></div>
          </section>
          <section class="panel details-panel" style="margin-top:18px">
            <h2>Import Existing Model</h2>
            <p class="section-desc">Enter a folder path on the backend computer, inside MODELS_DIR. This does not upload a model from the browser.</p>
            <label class="modal-label">Model name</label><input class="modal-input" v-model="importName" placeholder="My local MOSS"/>
            <label class="modal-label">Folder path</label><input class="modal-input" v-model="importPath" placeholder="D:\\models\\moss-tts"/>
            <label class="modal-label">Precision</label><select class="modal-input" v-model="importPrecision"><option value="bf16">BF16</option><option value="fp32">FP32</option><option value="int8">INT8 (validation unavailable)</option></select>
            <button class="button primary" style="margin-top:12px" :disabled="modelBusy || !importName.trim() || !importPath.trim()" @click="modelAction('import')">Import Existing Model</button>
          </section>
        </template>

        <template v-if="page === 'api'"><div class="page-header"><div><div class="eyebrow"><Code2 :size="14"/> DEVELOPER TOOLS</div><h1>API <em>Integration.</em></h1><p>เรียกใช้ Voice Studio จาก Anime AI Companion หรือแอปอื่น ๆ ด้วย HTTP API</p></div></div><div class="panel details-panel"><div class="results-heading"><h2><KeyRound :size="20" class="heading-icon"/> Local API</h2><span class="waiting-tag">REST · WAV / Live PCM</span></div><div class="endpoint"><span class="method post">POST</span><code>/v1/jobs</code><button class="icon-button" @click="copy('/v1/jobs')"><Copy :size="16"/></button></div><p class="section-desc">ส่งข้อความ ภาษา และ Voice ID จากคลังเสียง คืน Job ID เพื่อใช้ตรวจสถานะ</p><div class="code-head"><span>REQUEST BODY</span><button @click="copy(JSON.stringify({text:'สวัสดีค่ะ', language:'Thai', voice_id: selectedVoice || null},null,2))"><Copy :size="14"/> Copy</button></div><pre class="code-block">{{ JSON.stringify({text:'สวัสดีค่ะ', language:'Thai', voice_id: selectedVoice || null},null,2) }}</pre><div class="endpoint"><span class="method get">GET</span><code>/v1/jobs/:id</code></div><div class="endpoint"><span class="method get">GET</span><code>/v1/jobs/:id/audio</code></div><div class="endpoint"><span class="method post">POST</span><code>/v1/stream</code></div><p class="section-desc">SGLang-Omni progressive audio stream: raw PCM s16le mono 48 kHz, with language, voice_id, and optional instructions.</p><div class="endpoint"><span class="method get">GET</span><code>/v1/stream/status</code></div><div class="endpoint"><span class="method get">GET</span><code>/v1/voice-models</code></div><div class="endpoint"><span class="method post">POST</span><code>/v1/voice-models</code></div><p class="section-desc">Build from a completed job or Voice Profile; generate with voice_model_id and without MOSS model_id.</p><div class="endpoint"><span class="method get">GET</span><code>/v1/voices</code></div><div class="endpoint"><span class="method post">POST</span><code>/v1/voices</code></div><div class="model-note"><ShieldCheck :size="18"/><div><strong>Authentication</strong><p>ทุก request ต้องมี header <code>X-API-Key</code> สำหรับการใช้งานจริง ให้เรียกผ่าน Backend-to-Backend ไม่ควรฝัง secret ในเว็บที่เปิดสาธารณะ</p></div></div></div></template>
        <footer class="page-footer"><span>MOSS Voice Studio · Built for local AI creativity</span><span>Open-source model · Phase 3</span></footer>
      </div>
    </main>

    <div v-if="uploadOpen" class="modal-overlay" @click.self="uploadOpen = false"><div class="modal"><div class="modal-top"><div><div class="eyebrow">NEW VOICE PROFILE</div><h2>Add reference voice</h2><p>สร้างโปรไฟล์เสียงสำหรับ Zero-shot Voice Cloning</p></div><button class="icon-button" @click="uploadOpen=false"><X :size="19"/></button></div><label class="modal-label">Voice name</label><input class="modal-input" v-model="uploadName" maxlength="80" placeholder="เช่น Yuna, Narrator A"/><label class="modal-label">Character preset (optional)</label><input class="modal-input" v-model="uploadCharacter" maxlength="80" placeholder="Yuna / companion profile"/><label class="modal-label">Reference language</label><select class="modal-input" v-model="uploadLanguage"><option value="Thai">🇹🇭 Thai</option><option value="English">🇺🇸 English</option></select><label class="modal-label">Reference transcript (recommended for cloning)</label><textarea class="modal-input" rows="2" v-model="uploadTranscript" maxlength="1000" placeholder="พิมพ์ข้อความที่พูดจริงในเสียงต้นฉบับ"></textarea><label class="modal-label">Reference audio</label><input type="file" class="hidden-input" accept=".wav,audio/wav" ref="pickedFileInput" @change="fileChange"/><div class="modal-file" @click="pickedFileInput?.click()"><UploadCloud :size="24"/><strong>{{ uploadFile?.name || 'Click to choose a WAV file' }}</strong><span>PCM WAV · 1–60 seconds · recommended 3–20 seconds · up to 30 MB</span></div><label class="consent"><input type="checkbox" v-model="uploadConsent"/><span>ฉันมีสิทธิ์หรือได้รับความยินยอมให้ใช้เสียงนี้เพื่อสร้างเสียงสังเคราะห์</span></label><div class="modal-actions"><button class="button ghost" @click="uploadOpen=false">Cancel</button><button class="button primary" :disabled="uploading" @click="uploadVoice"><UploadCloud :size="17"/> {{ uploading ? 'Uploading...' : 'Save Voice Profile' }}</button></div></div></div>
  </div>
</template>
