/**
 * Progressive PCM s16le mono player for MOSS/SGLang 48k and Chatterbox 24k.
 * Each chunk is scheduled as an AudioBufferSourceNode; chunks do not wait for
 * the final response. AudioContext resamples 48k input for the user's device.
 */
export async function playPcmResponse(
  response: Response,
  context: AudioContext,
  signal: AbortSignal,
  onChunk: (bytes: number) => void,
  destination: AudioNode = context.destination,
): Promise<void> {
  const encoding = response.headers.get('X-Audio-Encoding')
  const rate = Number(response.headers.get('X-Sample-Rate') ?? '48000')
  const channels = Number(response.headers.get('X-Channels') ?? '1')
  if (encoding !== 'pcm_s16le' || ![24000, 48000].includes(rate) || channels !== 1)
    throw new Error('Unexpected PCM format. Expected signed 16-bit mono 24/48 kHz')
  if (!response.body) throw new Error('Streaming is not supported in this browser')
  const reader = response.body.getReader()
  let carry: number | null = null
  let playAt = context.currentTime + 0.12
  try {
    while (true) {
      if (signal.aborted) throw new DOMException('Cancelled', 'AbortError')
      const { done, value } = await reader.read()
      if (done) break
      if (!value?.length) continue
      const bytes: Uint8Array = new Uint8Array(value.length + (carry === null ? 0 : 1))
      if (carry !== null) bytes[0] = carry
      bytes.set(value, carry === null ? 0 : 1)
      const available: number = bytes.length - (bytes.length % 2)
      carry = available < bytes.length ? bytes[available] : null
      if (!available) continue
      const samples = available / 2
      const audio = context.createBuffer(1, samples, rate)
      const data = audio.getChannelData(0)
      for (let i = 0; i < samples; i++) {
        const raw = bytes[i * 2] | (bytes[i * 2 + 1] << 8)
        data[i] = (raw > 32767 ? raw - 65536 : raw) / 32768
      }
      const node = context.createBufferSource()
      node.buffer = audio
      node.connect(destination)
      playAt = Math.max(playAt, context.currentTime + 0.025)
      node.start(playAt)
      playAt += samples / rate
      onChunk(available)
    }
    if (carry !== null) throw new Error('Incomplete PCM sample received')
    const remaining = Math.max(0, (playAt - context.currentTime) * 1000)
    if (remaining) await new Promise<void>((resolve, reject) => {
      const timeout = setTimeout(() => {
        signal.removeEventListener('abort', cancelled)
        resolve()
      }, remaining)
      function cancelled() {
        clearTimeout(timeout)
        reject(new DOMException('Cancelled', 'AbortError'))
      }
      signal.addEventListener('abort', cancelled, { once: true })
    })
  } finally {
    await reader.cancel().catch(() => undefined)
  }
}
