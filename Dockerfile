# YingMusic-SVC RunPod Serverless — endpoint isolado pra teste
# Build context = root deste repo (fork de GiantAILab/YingMusic-SVC).
# NÃO afeta o endpoint principal STUDIO-MV (image separada).
FROM nvidia/cuda:12.1.0-cudnn8-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV HF_HUB_CACHE=/app/checkpoints/hf_cache
ENV TORCH_HOME=/app/checkpoints/torch
ENV PIP_NO_CACHE_DIR=1

# System deps + build tools (necessário pra webrtcvad e outras C extensions)
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3.10 python3-pip python3.10-venv python3.10-dev \
        git wget curl ca-certificates \
        ffmpeg sox libsox-fmt-all \
        libsndfile1 \
        build-essential gcc g++ make pkg-config \
        libportaudio2 portaudio19-dev \
    && ln -sf /usr/bin/python3.10 /usr/bin/python \
    && ln -sf /usr/bin/python3.10 /usr/bin/python3 \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app/YingMusic-SVC

# Copy YingMusic-SVC source (this repo IS the fork — code already here)
COPY . /app/YingMusic-SVC/

# PyTorch CUDA 12.1 (pinned, NÃO nightly)
RUN pip install --upgrade pip setuptools wheel \
    && pip install torch==2.4.0 torchvision==0.19.0 torchaudio==2.4.0 \
        --index-url https://download.pytorch.org/whl/cu121

# Strip torch pins do requirements.txt + remove nightly index URLs
RUN sed -i '/torch --pre/d;/torchvision --pre/d;/torchaudio --pre/d;/^torch==/d;/^torchvision==/d;/^torchaudio==/d' requirements.txt \
    && pip install -r requirements.txt

# RunPod SDK + R2 client
RUN pip install runpod==1.7.7 boto3==1.34.0

# Pre-download model weights pra build cache (cold start mais rápido)
RUN mkdir -p /app/checkpoints/hf_cache && \
    python -c "from huggingface_hub import snapshot_download; \
               snapshot_download('GiantAILab/YingMusic-SVC', cache_dir='/app/checkpoints/hf_cache', allow_patterns=['*.pt','*.ckpt','*.yml','*.yaml','*.json'])" \
    || echo "[WARN] HF pre-download failed (will retry at runtime)"

# Copy our RunPod handler last
COPY runpod_handler.py /app/handler.py
COPY runpod_r2_storage.py /app/r2_storage.py

WORKDIR /app
CMD ["python", "-u", "handler.py"]
