
"""MOSS-TTS inference engine with SoundFile WAV compatibility."""

import importlib.util
import threading
from pathlib import Path

from .config import settings


def patch_torchaudio_wav_loader() -> None:
    """Use SoundFile for WAV files to bypass TorchCodec."""
    import torch
    import torchaudio
    import soundfile as sf

    if getattr(torchaudio, "_moss_wav_patched", False):
        return

    original_load = torchaudio.load

    def load_wav(
        uri,
        frame_offset=0,
        num_frames=-1,
        normalize=True,
        channels_first=True,
        format=None,
        **kwargs,
    ):
        if isinstance(uri, (str, Path)) and Path(uri).suffix.lower() == ".wav":
            with sf.SoundFile(str(uri)) as audio_file:
                audio_file.seek(frame_offset)

                frames = (
                    num_frames
                    if num_frames is not None and num_frames > 0
                    else -1
                )

                data = audio_file.read(
                    frames=frames,
                    dtype="float32",
                    always_2d=True,
                )
                sample_rate = audio_file.samplerate

            if channels_first:
                data = data.T

            return torch.from_numpy(data.copy()), sample_rate

        return original_load(
            uri,
            frame_offset=frame_offset,
            num_frames=num_frames,
            normalize=normalize,
            channels_first=channels_first,
            format=format,
            **kwargs,
        )

    # These lines must remain inside patch_torchaudio_wav_loader.
    torchaudio.load = load_wav
    torchaudio._moss_wav_patched = True


class MossEngine:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._model = None
        self.loaded_model_id = None
        self._processor = None
        self.device_name = "not loaded"
        self.state = "not_loaded"
        self.last_error: str | None = None

    def unload(self) -> None:
        with self._lock:
            self._model = None
            self._processor = None
            self.loaded_model_id = None
            self.state = "not_loaded"
            self.device_name = "not loaded"
            import gc
            gc.collect()
            try:
                import torch
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except ImportError:
                pass

    def load_model(self, selected: dict) -> None:
        with self._lock:
            self._load(selected)

    def _load(self, selected: dict) -> None:
        if self._model is not None and self.loaded_model_id == selected["id"]:
            return
        if self._model is not None:
            self.unload()
        if selected["precision"] == "int8":
            raise RuntimeError("INT8 checkpoint loading is not supported by this MOSS runtime")


        self.state = "loading"
        self.last_error = None

        try:
            import torch
            from transformers import AutoModel, AutoProcessor

            torch.backends.cuda.enable_cudnn_sdp(False)
            torch.backends.cuda.enable_flash_sdp(True)
            torch.backends.cuda.enable_mem_efficient_sdp(True)
            torch.backends.cuda.enable_math_sdp(True)

            device = (
                "cuda" if torch.cuda.is_available() else "cpu"
            ) if settings.moss_device == "auto" else settings.moss_device

            self.device_name = device
            dtype = torch.bfloat16 if device.startswith("cuda") else torch.float32
            attn = "sdpa" if device.startswith("cuda") else "eager"

            if device.startswith("cuda") and importlib.util.find_spec("flash_attn"):
                if torch.cuda.get_device_capability()[0] >= 8:
                    attn = "flash_attention_2"

            processor = AutoProcessor.from_pretrained(
                selected["model_path"],
                trust_remote_code=True,
            )
            processor.audio_tokenizer = processor.audio_tokenizer.to(device)

            model = AutoModel.from_pretrained(
                selected["model_path"],
                trust_remote_code=True,
                attn_implementation=attn,
                torch_dtype=dtype,
            ).to(device)

            model.eval()

            self._processor = processor
            self._model = model
            self.loaded_model_id = selected["id"]
            self.state = "ready"

        except Exception as exc:
            self.state = "error"
            self.last_error = str(exc)
            raise

    def synthesize(
        self,
        text: str,
        language: str,
        reference: Path | None,
        output: Path,
        generation: dict | None = None,
        selected_model: dict | None = None,
    ) -> None:
        with self._lock:
            # Patch before processing any reference audio.
            patch_torchaudio_wav_loader()

            if selected_model is None:
                from .model_manager import resolve_model
                selected_model = resolve_model()
            self._load(selected_model)

            import torch
            import soundfile as sf

            options = {"text": text, "language": language}
            if reference is not None:
                options["reference"] = [str(reference)]

            request = self._processor.build_user_message(**options)
            batch = self._processor([[request]], mode="generation")

            input_ids = batch["input_ids"].to(self.device_name)
            attention_mask = batch["attention_mask"].to(self.device_name)

            with torch.inference_mode():
                generation = generation or {}

                output_tokens = self._model.generate(
                    input_ids=input_ids,
                    attention_mask=attention_mask,
                    max_new_tokens=settings.moss_max_new_tokens,
                    do_sample=True,
                    audio_temperature=generation.get("temperature", 1.7),
                    audio_top_p=generation.get("top_p", 0.8),
                    audio_top_k=generation.get("top_k", 25),
                    audio_repetition_penalty=generation.get(
                        "repetition_penalty", 1.0
                    ),
                )

                messages = self._processor.decode(output_tokens)

                audio = next(
                    (
                        m.audio_codes_list[0]
                        for m in messages
                        if m and m.audio_codes_list
                    ),
                    None,
                )

                if audio is None:
                    raise RuntimeError(
                        "Model did not return decoded audio. Try a shorter text."
                    )

                output.parent.mkdir(parents=True, exist_ok=True)

                waveform = audio.detach().float().cpu().numpy()

                if waveform.ndim == 2:
                    waveform = waveform.T
                elif waveform.ndim != 1:
                    raise RuntimeError(
                        f"Unexpected audio shape: {waveform.shape}"
                    )

                sf.write(
                    file=str(output),
                    data=waveform,
                    samplerate=self._processor.model_config.sampling_rate,
                    subtype="PCM_16",
                    format="WAV",
                )


engine = MossEngine()
