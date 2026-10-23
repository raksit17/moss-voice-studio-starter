# Chatterbox-Turbo GPU runtime (Linux x86_64, Python 3.11).
# The API stays lightweight, while the CUDA/PyTorch worker uses its own venv.
# MOSS 5B and F5-TTS runtimes are intentionally NOT installed in this image.
FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HOME=/cache/huggingface

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        git ffmpeg libsndfile1 libgomp1 ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt requirements-chatterbox.txt ./

# Separate runtime avoids loading Torch into the FastAPI interpreter.
RUN python -m pip install --no-cache-dir -r requirements.txt \
    && python -m venv /opt/venvs/chatterbox \
    && /opt/venvs/chatterbox/bin/python -m pip install --no-cache-dir --upgrade pip \
    && /opt/venvs/chatterbox/bin/python -m pip install --no-cache-dir \
        torch==2.6.0 torchaudio==2.6.0 \
        --index-url https://download.pytorch.org/whl/cu124 \
    && /opt/venvs/chatterbox/bin/python -m pip install --no-cache-dir -r requirements-chatterbox.txt \
    && /opt/venvs/chatterbox/bin/python -m pip check

COPY app ./app

RUN mkdir -p /app/data /app/models /cache/huggingface

EXPOSE 8001
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
