"""Production-backed inference adapter aligned with the official HF model card.

No synthetic/dummy audio is generated. Heavy libraries and weights load on first job.
"""
import importlib.util
import threading
from pathlib import Path
from .config import settings


class MossEngine:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._model = None
        self._processor = None
        self.device_name = 'not loaded'
        self.state = 'not_loaded'
        self.last_error: str | None = None

    def _load(self) -> None:
        if self._model is not None:
            return
        self.state = 'loading'
        self.last_error = None
        try:
            import torch
            from transformers import AutoModel, AutoProcessor

            torch.backends.cuda.enable_cudnn_sdp(False)
            torch.backends.cuda.enable_flash_sdp(True)
            torch.backends.cuda.enable_mem_efficient_sdp(True)
            torch.backends.cuda.enable_math_sdp(True)

            device = ('cuda' if torch.cuda.is_available() else 'cpu') if settings.moss_device == 'auto' else settings.moss_device
            self.device_name = device
            dtype = torch.bfloat16 if device.startswith('cuda') else torch.float32
            attn = 'sdpa' if device.startswith('cuda') else 'eager'
            if device.startswith('cuda') and importlib.util.find_spec('flash_attn'):
                if torch.cuda.get_device_capability()[0] >= 8:
                    attn = 'flash_attention_2'

            processor = AutoProcessor.from_pretrained(settings.moss_model_id, trust_remote_code=True)
            processor.audio_tokenizer = processor.audio_tokenizer.to(device)
            model = AutoModel.from_pretrained(
                settings.moss_model_id,
                trust_remote_code=True,
                attn_implementation=attn,
                torch_dtype=dtype,
            ).to(device)
            model.eval()
            self._processor = processor
            self._model = model
            self.state = 'ready'
        except Exception as exc:
            self.state = 'error'
            self.last_error = str(exc)
            raise

    def synthesize(self, text: str, language: str, reference: Path | None, output: Path,
                   generation: dict | None = None) -> None:
        # Single inference at a time: safeguards against GPU OOM on a local workstation.
        with self._lock:
            self._load()
            import torch
            import torchaudio

            options = {'text': text, 'language': language}
            if reference is not None:
                options['reference'] = [str(reference)]
            request = self._processor.build_user_message(**options)
            batch = self._processor([[request]], mode='generation')
            input_ids = batch['input_ids'].to(self.device_name)
            attention_mask = batch['attention_mask'].to(self.device_name)
            with torch.inference_mode():
                generation = generation or {}
                output_tokens = self._model.generate(
                    input_ids=input_ids,
                    attention_mask=attention_mask,
                    max_new_tokens=settings.moss_max_new_tokens,
                    do_sample=True,
                    audio_temperature=generation.get('temperature', 1.7),
                    audio_top_p=generation.get('top_p', 0.8),
                    audio_top_k=generation.get('top_k', 25),
                    audio_repetition_penalty=generation.get('repetition_penalty', 1.0),
                )
                messages = self._processor.decode(output_tokens)
                audio = next((m.audio_codes_list[0] for m in messages if m and m.audio_codes_list), None)
                if audio is None:
                    raise RuntimeError('Model did not return decoded audio. Try a shorter text.')
                output.parent.mkdir(parents=True, exist_ok=True)
                # MOSS 1.5: stereo tensor [channels, samples] at 48kHz.
                torchaudio.save(str(output), audio.detach().cpu(), self._processor.model_config.sampling_rate)


engine = MossEngine()
