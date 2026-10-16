/**
 * Phase 3 adapter for anime-ai-companion (browser-side).
 * Copy together with pcm-player.ts or adapt imports. Audio must come from a
 * NestJS proxy: never embed the production Voice Studio API key in the browser.
 */
import { playPcmResponse } from './pcm-player'

export type CompanionSegment =
  | { type: 'speech'; text: string; language?: 'Thai' | 'English'; emotion?: string }
  | { type: 'action'; expression?: string; motion?: string }

export interface Live2DControls {
  // Map lip 0..1 to your character's parameter (e.g. ParamA).
  setMouthOpen: (amount: number) => void
  setEmotion?: (emotion: string) => void
  applyAction?: (action: { expression?: string; motion?: string }) => void | Promise<void>
}

export interface PlaybackOptions {
  context: AudioContext
  adapter: Live2DControls
  signal: AbortSignal
  segments: CompanionSegment[]
  /** Fetch a raw 48kHz mono pcm_s16le stream from your NestJS proxy. */
  requestSpeech: (segment: Extract<CompanionSegment, { type: 'speech' }>,
                  index: number, signal: AbortSignal) => Promise<Response>
  onSegment?: (index: number, type: CompanionSegment['type'], status: 'start' | 'end') => void
}

/** Plays speech/action sequentially, using *played audio* to animate lip sync. */
export async function playCompanionSegments(options: PlaybackOptions): Promise<void> {
  const { context, adapter, signal, segments, requestSpeech, onSegment } = options
  await context.resume()
  const analyser = context.createAnalyser()
  analyser.fftSize = 1024
  analyser.smoothingTimeConstant = 0.55
  analyser.connect(context.destination)
  const samples = new Float32Array(analyser.fftSize)
  let cancelled = false
  let currentIsSpeech = false
  let frameId: number | null = null

  const tick = () => {
    if (cancelled || signal.aborted) return
    if (currentIsSpeech) {
      analyser.getFloatTimeDomainData(samples)
      let total = 0
      for (let i = 0; i < samples.length; i++) total += samples[i] * samples[i]
      const rms = Math.sqrt(total / samples.length)
      adapter.setMouthOpen(Math.max(0, Math.min(1, rms * 7)))
    } else {
      adapter.setMouthOpen(0)
    }
    frameId = requestAnimationFrame(tick)
  }
  frameId = requestAnimationFrame(tick)

  try {
    for (let index = 0; index < segments.length; index++) {
      if (signal.aborted) throw new DOMException('Playback interrupted', 'AbortError')
      const segment = segments[index]
      onSegment?.(index, segment.type, 'start')
      if (segment.type === 'action') {
        await adapter.applyAction?.({
          expression: segment.expression,
          motion: segment.motion,
        })
      } else if (segment.text.trim()) {
        if (segment.emotion) adapter.setEmotion?.(segment.emotion)
        const response = await requestSpeech(segment, index, signal)
        currentIsSpeech = true
        try {
          await playPcmResponse(response, context, signal, () => undefined, analyser)
        } finally {
          currentIsSpeech = false
          adapter.setMouthOpen(0)
        }
      }
      onSegment?.(index, segment.type, 'end')
    }
  } finally {
    cancelled = true
    if (frameId !== null) cancelAnimationFrame(frameId)
    adapter.setMouthOpen(0)
    analyser.disconnect()
  }
}
