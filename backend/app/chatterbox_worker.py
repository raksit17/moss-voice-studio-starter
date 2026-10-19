"""Isolated persistent JSONL process for the official Resemble Chatterbox-Turbo."""
import contextlib
import json
import os
import sys
from pathlib import Path

_model = None
_device = None


def _patch_wav_loader():
    # Avoid TorchCodec/FFmpeg DLL failures for local PCM reference WAVs on Windows.
    import torch
    import torchaudio
    import soundfile as sf
    original = torchaudio.load

    def load(uri, frame_offset=0, num_frames=-1, normalize=True,
             channels_first=True, format=None, **kwargs):
        if isinstance(uri, (str, Path)) and Path(uri).suffix.lower() == ".wav":
            with sf.SoundFile(str(uri)) as file:
                file.seek(frame_offset)
                audio = file.read(frames=num_frames if num_frames > 0 else -1,
                                  dtype="float32", always_2d=True)
                sr = file.samplerate
            tensor = torch.from_numpy(audio.T.copy() if channels_first else audio.copy())
            return tensor, sr
        return original(uri, frame_offset=frame_offset, num_frames=num_frames,
                        normalize=normalize, channels_first=channels_first,
                        format=format, **kwargs)

    torchaudio.load = load


def _load():
    global _model, _device
    if _model is None:
        import torch
        from chatterbox.tts_turbo import ChatterboxTurboTTS
        selected = os.getenv("CHATTERBOX_DEVICE", "auto").lower()
        if selected not in ("auto", "cpu", "cuda"):
            raise ValueError("CHATTERBOX_DEVICE must be auto, cpu or cuda")
        _device = ("cuda" if torch.cuda.is_available() else "cpu") if selected == "auto" else selected
        if _device == "cuda" and not torch.cuda.is_available():
            raise RuntimeError("Chatterbox CUDA requested but unavailable")
        _patch_wav_loader()
        _model = ChatterboxTurboTTS.from_pretrained(device=_device)
    return _model


def _handle(command):
    if command.get("command") == "load":
        _load()
        return {"ok": True, "device": _device}
    if command.get("command") != "synthesize":
        raise ValueError("Invalid worker command")
    content = command.get("text")
    if not isinstance(content, str) or not 1 <= len(content.strip()) <= 600:
        raise ValueError("Text must be 1-600 characters")
    reference = command.get("reference_wav")
    if reference is not None and (not isinstance(reference, str) or
                                  not Path(reference).is_file()):
        raise ValueError("Reference WAV file is missing")
    output = Path(command["output_wav"])
    model = _load()
    import torch
    import soundfile as sf
    with torch.inference_mode():
        if reference:
            waveform = model.generate(content, audio_prompt_path=reference)
        else:
            waveform = model.generate(content)
    audio = waveform.detach().float().cpu().numpy()
    if audio.ndim == 2:
        audio = audio.T
    elif audio.ndim != 1:
        raise RuntimeError(f"Unexpected Chatterbox waveform shape: {audio.shape}")
    output.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(output), audio, model.sr, format="WAV", subtype="PCM_16")
    return {"ok": True, "device": _device, "sample_rate": model.sr}


def main():
    # stdout is protocol-only; library progress and download output go to log stderr.
    for line in sys.stdin:
        try:
            command = json.loads(line)
            with contextlib.redirect_stdout(sys.stderr):
                result = _handle(command)
        except Exception as error:
            import traceback
            traceback.print_exc(file=sys.stderr)
            result = {"ok": False, "error": str(error)[:500]}
        sys.stdout.write(json.dumps(result, ensure_ascii=False) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
