/**
 * Copy to anime-ai-companion NestJS backend and adapt module imports/guards.
 * Production authentication and authorization are handled by your app.
 * No Voice Studio API key is ever sent to the browser.
 */
import { Body, Controller, Post, Res } from '@nestjs/common'
import type { Response } from 'express'
import { once } from 'node:events'
import { VoiceStudioClient } from './anime-ai-companion-integration'

interface SpeechRequest {
  text: string
  voiceId: string | null
  language: 'Thai' | 'English'
  instructions?: string
}

@Controller('companion/voice')
export class CompanionVoiceController {
  constructor(private readonly studio: VoiceStudioClient) {}

  @Post('stream')
  async stream(@Body() body: SpeechRequest, @Res() response: Response) {
    const abort = new AbortController()
    response.once('close', () => abort.abort())
    // Upstream must reply successfully before downstream headers are sent.
    const upstream = await this.studio.synthesizeStream(
      body.text, body.voiceId, body.language, abort.signal, body.instructions,
    )
    response.setHeader('Content-Type', 'application/octet-stream')
    response.setHeader('X-Audio-Encoding', 'pcm_s16le')
    response.setHeader('X-Sample-Rate', '48000')
    response.setHeader('X-Channels', '1')
    response.setHeader('Cache-Control', 'no-store')
    response.flushHeaders()
    try {
      // Do NOT await response.arrayBuffer()—that would defeat streaming.
      for await (const chunk of upstream.body!) {
        if (abort.signal.aborted) break
        if (!response.write(Buffer.from(chunk))) await once(response, 'drain')
      }
    } finally {
      await upstream.body?.cancel().catch(() => undefined)
      if (!response.writableEnded) response.end()
    }
  }
}
