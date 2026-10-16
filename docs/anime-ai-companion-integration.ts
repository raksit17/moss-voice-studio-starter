/**
 * Server-side NestJS service example: apps/api/src/modules/voice/voice-studio.client.ts
 * Keep VOICE_STUDIO_API_KEY on the SERVER, not in frontend environment variables.
 * Node.js 20+ global fetch. Tailor constructor injection to your existing project.
 */
import { Injectable, InternalServerErrorException } from '@nestjs/common';

interface StartJob { id: string; status: string }
interface JobStatus {
  id: string;
  status: 'queued' | 'running' | 'completed' | 'failed';
  error?: string | null;
  audio_url?: string | null;
}

@Injectable()
export class VoiceStudioClient {
  private readonly baseUrl = process.env.VOICE_STUDIO_URL || 'http://127.0.0.1:8001';
  private readonly apiKey = process.env.VOICE_STUDIO_API_KEY || '';

  private async call(path: string, init: RequestInit = {}): Promise<Response> {
    if (!this.apiKey) throw new Error('VOICE_STUDIO_API_KEY is missing');
    const result = await fetch(`${this.baseUrl}${path}`, {
      ...init,
      headers: { 'X-API-Key': this.apiKey, ...init.headers },
      signal: init.signal,
    });
    if (!result.ok) throw new InternalServerErrorException(`Voice Studio HTTP ${result.status}`);
    return result;
  }

  async synthesize(text: string, voiceId: string | null, language: 'Thai' | 'English'): Promise<Buffer> {
    const started = await this.call('/v1/jobs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, voice_id: voiceId, language }),
    });
    const { id } = (await started.json()) as StartJob;
    const deadline = Date.now() + 240_000;
    while (Date.now() < deadline) {
      const response = await this.call(`/v1/jobs/${id}`);
      const status = (await response.json()) as JobStatus;
      if (status.status === 'completed') {
        const audio = await this.call(`/v1/jobs/${id}/audio`);
        return Buffer.from(await audio.arrayBuffer());
      }
      if (status.status === 'failed') throw new Error(status.error || 'TTS failed');
      await new Promise(resolve => setTimeout(resolve, 1500));
    }
    throw new Error(`Voice Studio timed out: job ${id}`);
  }
}

// Example flow:
// - For AI response segment { type: 'speech', text: 'สวัสดีค่ะ', emotion: 'happy' }
// - call voiceStudioClient.synthesize(segment.text, yunaVoiceId, 'Thai')
// - return WAV bytes from a NestJS controller with Content-Type: audio/wav
// - use decoded WebAudio RMS to drive Live2D ParamA (lip-sync) during playback
// - for { type: 'action' }, trigger Live2D expression/motion ONLY, not TTS
// NOTE: The v0.1 API is non-streaming; do not present this as low-latency streaming.
