
"""F5-TTS-THAI child entrypoint; loads weights only inside this process."""

import json
import sys
from pathlib import Path


def main() -> None:
    payload = json.load(sys.stdin)

    import numpy as np
    import soundfile as sf
    import torch
    import torchaudio

    # Compatibility patch:
    # Read reference WAV without TorchCodec / FFmpeg shared DLLs.
    original_load = torchaudio.load

    def load_wav_without_torchcodec(
        uri,
        frame_offset=0,
        num_frames=-1,
        normalize=True,
        channels_first=True,
        format=None,
        buffer_size=4096,
        backend=None,
    ):
        path = Path(uri)

        if path.suffix.lower() != ".wav":
            raise RuntimeError(
                "F5 reference audio must be WAV when using SoundFile."
            )

        with sf.SoundFile(str(path)) as file:
            sample_rate = file.samplerate

            if frame_offset > 0:
                file.seek(frame_offset)

            frames = -1 if num_frames == -1 else num_frames

            data = file.read(
                frames=frames,
                dtype="float32",
                always_2d=True,
            )

        # SoundFile: [samples, channels]
        # Torchaudio: [channels, samples]
        audio = torch.from_numpy(
            np.ascontiguousarray(data.T)
        )

        if not channels_first:
            audio = audio.T.contiguous()

        return audio, sample_rate

    # Patch only within the F5 subprocess.
    torchaudio.load = load_wav_without_torchcodec

    # Import F5 after applying the patch.
    from f5_tts_th.tts import TTS

    model = TTS(model="v1")

    audio = model.infer(
        ref_audio=payload["reference_wav"],
        ref_text=payload["reference_text"],
        gen_text=payload["text"],
        step=32,
        cfg=2.0,
        speed=1.0,
    )

    output = Path(payload["output_wav"])
    output.parent.mkdir(parents=True, exist_ok=True)

    if isinstance(audio, torch.Tensor):
        audio = audio.detach().cpu().numpy()

    sf.write(
        str(output),
        audio,
        24000,
        subtype="PCM_16",
    )


if __name__ == "__main__":
    main()
