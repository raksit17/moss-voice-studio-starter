# The API/MOSS and English Chatterbox runtimes have incompatible pinned
# PyTorch/transformers versions, so Chatterbox runs in its own Python venv.
FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HOME=/root/.cache/huggingface

WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates ffmpeg libsndfile1 libgomp1 git build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt backend/requirements-moss.txt backend/requirements-chatterbox.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cu128 \
       torch==2.9.1+cu128 torchaudio==2.9.1+cu128 torchcodec==0.8.1 \
    && pip install --no-cache-dir -r requirements-moss.txt

ARG INSTALL_CHATTERBOX=true
RUN if [ "$INSTALL_CHATTERBOX" = "true" ]; then \
      python -m venv /opt/chatterbox && \
      /opt/chatterbox/bin/pip install --no-cache-dir -r requirements-chatterbox.txt; \
    fi

COPY backend/app ./app
EXPOSE 8001
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001", "--workers", "1"]
