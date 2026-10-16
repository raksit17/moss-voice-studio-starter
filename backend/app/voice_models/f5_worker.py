"""F5-TTS-THAI child entrypoint; loads weights only inside this process."""
import json
import sys
from pathlib import Path


def main() -> None:
    payload = json.load(sys.stdin)
    import soundfile as sf
    from f5_tts_th.tts import TTS

    model = TTS(model='v1')
    audio = model.infer(
        ref_audio=payload['reference_wav'],
        ref_text=payload['reference_text'],
        gen_text=payload['text'],
        step=32,
        cfg=2.0,
        speed=1.0,
    )
    output = Path(payload['output_wav'])
    output.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(output), audio, 24000, subtype='PCM_16')


if __name__ == '__main__':
    main()
