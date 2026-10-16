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
} from './api'
import { playPcmResponse } from './pcm-player'

type Page = 'studio' | 'voices' | 'history' | 'model' | 'api'
const page = ref<Page>('studio')
const sidebarOpen = ref(false)
const health = ref<Health | null>(null)
const online = ref(false)
const voices = ref<Voice[]>([])
const jobs = ref<Job[]>([])
const selectedVoice = ref('')
const language = ref<'Thai' | 'English'>('Thai')
const text = ref('กลับมาแล้วเหรอคะ... ฉันกำลังรอคุณอยู่พอดีเลย วันนี้มีอะไรอยากเล่าให้ฟังไหมคะ?')
const notification = ref('')
const error = ref('')
const creating = ref(false)
const activeJobId = ref<string | null>(null)
const playerUrl = ref<string | null>(null)
const player = ref<HTMLAudioElement | null>(null)
const playing = ref(false)
const uploadOpen = ref(false)
const uploadName = ref('')
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
const selectedVoiceName = computed(() => voices.value.find(v => v.id === selectedVoice.value)?.name ?? 'Default voice')
const latestJobs = computed(() => jobs.value.slice(0, 5))
const historyJobs = computed(() => jobs.value)
const dateLabel = (str: string) => new Date(str).toLocaleString('th-TH', { dateStyle: 'medium', timeStyle: 'short' })

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
    const [h, vs, js, st] = await Promise.all([getHealth(), getVoices(), getJobs(), getStreamStatus()])
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
    const job = await createJob(text.value.trim(), language.value, selectedVoice.value || null)
    activeJobId.value = job.id
    alertMessage('ส่งงานเข้า Voice Engine แล้ว — ดูสถานะได้ในรายการด้านล่าง')
    await refresh()
  } catch (e) {
    alertMessage((e as Error).message, 'error')
  } finally {
    creating.value = false
  }
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
    a.href = url; a.download = filename; a.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  } catch (e) { alertMessage((e as Error).message, 'error') }
}
async function uploadVoice() {
  if (!uploadFile.value || !uploadName.value.trim() || !uploadConsent.value) {
    return alertMessage('กรุณาระบุชื่อ เลือกไฟล์ WAV และยืนยันสิทธิ์ของเสียง', 'error')
  }
  uploading.value = true
  try {
    const voice = await createVoice(uploadName.value, uploadLanguage.value, uploadFile.value, uploadTranscript.value)
    uploadOpen.value = false
    uploadName.value = ''; uploadFile.value = null; uploadConsent.value = false; uploadTranscript.value = ''
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
      selectedVoice.value || null, liveInstructions.value, liveAbort.signal)
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
})
onUnmounted(() => {
  stopLive()
  if (timer) clearInterval(timer)
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
              <div class="stream-params"><label for="live-style">Streaming style hint (optional)</label><input id="live-style" v-model="liveInstructions" maxlength="240" placeholder="e.g. warm, gentle, cheerful" /><span>{{ liveStatus?.ready ? "● SGLang ready · progressive PCM 48 kHz mono" : "○ Streaming requires SGLang-Omni server" }}</span></div><div class="action-row"><div class="quality-mark"><ShieldCheck :size="17"/><div><strong>48 kHz · Stereo WAV</strong><span>High fidelity audio output</span></div></div><button class="button primary generate-btn" :disabled="creating || isBusy || !text.trim()" @click="generate"><Waves v-if="!creating && !isBusy" :size="18"/><RefreshCcw v-else :size="18" class="spin"/>{{ creating || isBusy ? 'Generating...' : 'Generate Speech' }}</button></div>
              <div class="stream-actions">
                <button v-if="!liveActive" class="button secondary" :disabled="!text.trim() || !liveStatus?.ready" @click="liveSpeak">
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
              <div class="voice-selection"><div class="voice-avatar"><AudioLines :size="24"/></div><div class="voice-select-text"><strong>{{ selectedVoiceName }}</strong><span>{{ selectedVoice ? 'Zero-shot voice cloning' : 'No reference voice' }}</span></div><ChevronDown :size="18" class="select-chevron"/><select v-model="selectedVoice"><option value="">Default voice</option><option v-for="voice in voices" :key="voice.id" :value="voice.id">{{ voice.name }}</option></select></div>
              <div class="upload-card" @click="uploadOpen = true"><div class="upload-icon"><UploadCloud :size="25"/></div><strong>Add your own voice</strong><span>อัปโหลดเสียง WAV ที่ได้รับอนุญาต เพื่อใช้สร้างเสียงพูดใหม่ด้วยบุคลิกเสียงเดิม</span><button class="upload-link">Upload reference audio <span>↗</span></button></div>
              <div class="settings-section"><h3><SlidersHorizontal :size="16"/> Model parameters</h3><div class="info-setting"><span>Temperature</span><strong>1.7 <small>Default</small></strong></div><div class="info-setting"><span>Top P / Top K</span><strong>0.8 / 25</strong></div><div class="info-setting"><span>Voice method</span><strong>Zero-shot</strong></div><p class="settings-note"><Info :size="14"/> ใช้ค่า Generation ที่ผู้พัฒนาแนะนำไว้ใน MVP นี้</p></div>
            </section>
          </div>

          <section class="panel results-panel"><div class="results-heading"><div><div class="panel-kicker">03 / OUTPUT</div><h2><Volume2 :size="20" class="heading-icon"/> Audio Preview</h2></div><span v-if="currentJob" class="status-tag" :class="currentJob.status">{{ currentJob.status }}</span><span v-else class="waiting-tag">Waiting for generation</span></div>
            <template v-if="currentJob && currentJob.status === 'completed'"><div class="audio-result"><div class="audio-result-icon"><FileAudio :size="22"/></div><div class="audio-info"><strong>Generated speech</strong><span>{{ currentJob.language }} · WAV · {{ dateLabel(currentJob.created_at) }}</span></div><button class="button ghost" @click="playAudio(currentJob.audio_url)"><Play :size="15"/> Play</button><button class="button secondary" @click="downloadAudio(currentJob.audio_url,`moss-${currentJob.id}.wav`)"><ArrowDownToLine :size="16"/> Download</button></div></template>
            <template v-else-if="currentJob && currentJob.status === 'failed'"><div class="empty-result failed-result"><Info :size="28"/><strong>Generation failed</strong><span>{{ currentJob.error }}</span></div></template>
            <template v-else-if="currentJob"><div class="empty-result"><div class="pulse-wave"><span></span><span></span><span></span><span></span><span></span></div><strong>กำลังสร้างเสียง</strong><span>รันโมเดลบนเครื่องและประมวลผลเสียง กรุณาดูสถานะในแถบนี้</span></div></template>
            <template v-else><div class="empty-result"><div class="empty-wave"><AudioLines :size="30"/></div><strong>Your voice is waiting to be created</strong><span>เลือกเสียง พิมพ์ข้อความ แล้วกด Generate Speech เพื่อเริ่มต้น</span></div></template>
            <audio v-if="playerUrl" ref="player" :src="playerUrl" controls class="html-player" @play="playing=true" @pause="playing=false" @ended="playing=false"></audio>
          </section>
        </template>

        <template v-if="page === 'voices'"><div class="page-header"><div><div class="eyebrow"><Library :size="14"/> YOUR LIBRARY</div><h1>Voice <em>Library.</em></h1><p>จัดการเสียงต้นแบบสำหรับ Zero-shot Voice Cloning และใช้ Voice ID กับแอปอื่น</p></div><button class="button primary" @click="uploadOpen = true"><Plus :size="17"/> Add a voice</button></div><div class="panel library-panel"><div class="results-heading"><div><h2><Mic2 :size="20" class="heading-icon"/> Saved profiles</h2><p>{{ voices.length }} voices available</p></div></div><div v-if="voices.length" class="voice-list"><div v-for="voice in voices" :key="voice.id" class="voice-item"><div class="voice-item-icon"><AudioLines :size="21"/></div><div class="voice-item-info"><strong>{{ voice.name }}</strong><span>{{ voice.language }} · {{ dateLabel(voice.created_at) }} · {{ voice.id.slice(0,8) }}</span></div><div class="voice-item-actions"><button class="small-button" @click="selectedVoice=voice.id; navigate('studio')"><WandSparkles :size="15"/> Use voice</button><button class="icon-button danger-icon" title="Delete voice" @click="removeVoice(voice)"><Trash2 :size="17"/></button></div></div></div><div v-else class="empty-result tall"><div class="empty-wave"><Mic2 :size="29"/></div><strong>No voices saved yet</strong><span>เพิ่มไฟล์เสียง WAV ที่มีสิทธิ์ใช้งาน เพื่อโคลนเสียงของตัวละคร</span><button class="button secondary" @click="uploadOpen=true"><UploadCloud :size="16"/> Upload reference</button></div></div></template>

        <template v-if="page === 'history'"><div class="page-header"><div><div class="eyebrow"><Clock3 :size="14"/> AUDIO OUTPUTS</div><h1>Generation <em>History.</em></h1><p>ตรวจสถานะงานย้อนหลัง เล่น และดาวน์โหลดไฟล์เสียงที่สร้างไว้</p></div><button class="button secondary" @click="refresh"><RefreshCcw :size="16"/> Refresh</button></div><div class="panel library-panel"><div class="results-heading"><h2><Headphones :size="20" class="heading-icon"/> Recent jobs</h2><span class="waiting-tag">{{ historyJobs.length }} records</span></div><div v-if="historyJobs.length" class="job-list"><div v-for="job in historyJobs" :key="job.id" class="job-item"><div class="job-icon"><FileAudio :size="20"/></div><div class="job-info"><strong>{{ job.text }}</strong><span>{{ job.language }} · {{ dateLabel(job.created_at) }}</span><small v-if="job.error" class="error-text">{{ job.error }}</small></div><span class="status-tag" :class="job.status">{{ job.status }}</span><button class="icon-button" :disabled="job.status !== 'completed'" @click="playAudio(job.audio_url)" title="Play"><Play :size="16"/></button><button class="icon-button" :disabled="job.status !== 'completed'" @click="downloadAudio(job.audio_url, `moss-${job.id}.wav`)" title="Download"><ArrowDownToLine :size="16"/></button></div></div><div v-else class="empty-result tall"><div class="empty-wave"><Clock3 :size="29"/></div><strong>No generations yet</strong><span>สร้างเสียงจากหน้า Playground แล้วผลลัพธ์จะอยู่ที่นี่</span><button class="button secondary" @click="navigate('studio')">Open Playground</button></div></div></template>

        <template v-if="page === 'model'"><div class="page-header"><div><div class="eyebrow"><Cpu :size="14"/> ENGINE CONFIGURATION</div><h1>Model <em>Manager.</em></h1><p>สถานะของ MOSS-TTS Local Transformer v1.5 และการดาวน์โหลดโมเดล</p></div><button class="button secondary" @click="refresh"><RefreshCcw :size="16"/> Check status</button></div><div class="panel details-panel"><div class="model-head"><div class="model-logo"><Waves :size="32"/></div><div><span class="panel-kicker">CURRENTLY CONFIGURED</span><h2>MOSS-TTS Local Transformer <span>v1.5</span></h2><p>OpenMOSS-Team · Apache 2.0 · Local model</p></div><span class="status-tag" :class="online ? 'completed' : 'failed'">{{ online ? 'API Online' : 'API Offline' }}</span></div><div class="model-stats"><div><small>Model ID</small><strong class="wrap-text">{{ health?.model || 'OpenMOSS-Team/MOSS-TTS-Local-Transformer-v1.5' }}</strong></div><div><small>Runtime status</small><strong>{{ health?.engine || 'Unknown' }}</strong></div><div><small>Device</small><strong>{{ health?.device || 'Not connected' }}</strong></div><div><small>Codec</small><strong>48 kHz · Stereo</strong></div></div><div class="model-note"><Info :size="18"/><div><strong>Lazy loading enabled</strong><p>โมเดลจะถูกโหลดเมื่อเริ่มสร้างเสียงครั้งแรก — สถานะ Standby ไม่ได้หมายความว่าดาวน์โหลดหรือโหลดโมเดลเรียบร้อยแล้ว</p></div></div><div class="model-links"><a target="_blank" rel="noreferrer" href="https://huggingface.co/OpenMOSS-Team/MOSS-TTS-Local-Transformer-v1.5">Model on Hugging Face ↗</a><a target="_blank" rel="noreferrer" href="https://github.com/OpenMOSS/MOSS-TTS">Official repository ↗</a></div></div></template>

        <template v-if="page === 'api'"><div class="page-header"><div><div class="eyebrow"><Code2 :size="14"/> DEVELOPER TOOLS</div><h1>API <em>Integration.</em></h1><p>เรียกใช้ Voice Studio จาก Anime AI Companion หรือแอปอื่น ๆ ด้วย HTTP API</p></div></div><div class="panel details-panel"><div class="results-heading"><h2><KeyRound :size="20" class="heading-icon"/> Local API</h2><span class="waiting-tag">REST · WAV / Live PCM</span></div><div class="endpoint"><span class="method post">POST</span><code>/v1/jobs</code><button class="icon-button" @click="copy('/v1/jobs')"><Copy :size="16"/></button></div><p class="section-desc">ส่งข้อความ ภาษา และ Voice ID จากคลังเสียง คืน Job ID เพื่อใช้ตรวจสถานะ</p><div class="code-head"><span>REQUEST BODY</span><button @click="copy(JSON.stringify({text:'สวัสดีค่ะ', language:'Thai', voice_id: selectedVoice || null},null,2))"><Copy :size="14"/> Copy</button></div><pre class="code-block">{{ JSON.stringify({text:'สวัสดีค่ะ', language:'Thai', voice_id: selectedVoice || null},null,2) }}</pre><div class="endpoint"><span class="method get">GET</span><code>/v1/jobs/:id</code></div><div class="endpoint"><span class="method get">GET</span><code>/v1/jobs/:id/audio</code></div><div class="endpoint"><span class="method post">POST</span><code>/v1/stream</code></div><p class="section-desc">SGLang-Omni progressive audio stream: raw PCM s16le mono 48 kHz, with language, voice_id, and optional instructions.</p><div class="endpoint"><span class="method get">GET</span><code>/v1/stream/status</code></div><div class="endpoint"><span class="method get">GET</span><code>/v1/voices</code></div><div class="endpoint"><span class="method post">POST</span><code>/v1/voices</code></div><div class="model-note"><ShieldCheck :size="18"/><div><strong>Authentication</strong><p>ทุก request ต้องมี header <code>X-API-Key</code> สำหรับการใช้งานจริง ให้เรียกผ่าน Backend-to-Backend ไม่ควรฝัง secret ในเว็บที่เปิดสาธารณะ</p></div></div></div></template>
        <footer class="page-footer"><span>MOSS Voice Studio · Built for local AI creativity</span><span>Open-source model · Phase 3</span></footer>
      </div>
    </main>

    <div v-if="uploadOpen" class="modal-overlay" @click.self="uploadOpen = false"><div class="modal"><div class="modal-top"><div><div class="eyebrow">NEW VOICE PROFILE</div><h2>Add reference voice</h2><p>สร้างโปรไฟล์เสียงสำหรับ Zero-shot Voice Cloning</p></div><button class="icon-button" @click="uploadOpen=false"><X :size="19"/></button></div><label class="modal-label">Voice name</label><input class="modal-input" v-model="uploadName" maxlength="80" placeholder="เช่น Yuna, Narrator A"/><label class="modal-label">Reference language</label><select class="modal-input" v-model="uploadLanguage"><option value="Thai">🇹🇭 Thai</option><option value="English">🇺🇸 English</option></select><label class="modal-label">Reference transcript (recommended for cloning)</label><textarea class="modal-input" rows="2" v-model="uploadTranscript" maxlength="1000" placeholder="พิมพ์ข้อความที่พูดจริงในเสียงต้นฉบับ"></textarea><label class="modal-label">Reference audio</label><input type="file" class="hidden-input" accept=".wav,audio/wav" ref="pickedFileInput" @change="fileChange"/><div class="modal-file" @click="pickedFileInput?.click()"><UploadCloud :size="24"/><strong>{{ uploadFile?.name || 'Click to choose a WAV file' }}</strong><span>PCM WAV · 1–60 seconds · recommended 3–20 seconds · up to 30 MB</span></div><label class="consent"><input type="checkbox" v-model="uploadConsent"/><span>ฉันมีสิทธิ์หรือได้รับความยินยอมให้ใช้เสียงนี้เพื่อสร้างเสียงสังเคราะห์</span></label><div class="modal-actions"><button class="button ghost" @click="uploadOpen=false">Cancel</button><button class="button primary" :disabled="uploading" @click="uploadVoice"><UploadCloud :size="17"/> {{ uploading ? 'Uploading...' : 'Save Voice Profile' }}</button></div></div></div>
  </div>
</template>
