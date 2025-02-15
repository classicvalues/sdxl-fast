FROM nvidia/cuda:12.1.0-runtime-ubuntu20.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt update && \
    apt install -y bash \
    build-essential \
    git \
    git-lfs \
    curl \
    ca-certificates \
    libsndfile1-dev \
    libgl1 \
    python3.8 \
    python3-pip \
    python3.8-venv && \
    rm -rf /var/lib/apt/lists

RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

RUN python3 -m pip install --no-cache-dir --upgrade pip && \
    python3 -m pip install --no-cache-dir --pre torch --index-url https://download.pytorch.org/whl/nightly/cu121 && \
    python3 -m pip install --no-cache-dir \
    accelerate \
    Jinja2 \
    transformers \
    peft \
    pandas \ 
    matplotlib

RUN python3 -m pip install --no-cache-dir git+https://github.com/huggingface/diffusers@4836cfad9836e6742a1d09462f85313534388a48
RUN python3 -m pip install --no-cache-dir git+https://github.com/pytorch-labs/ao@9aaf3ec704d659a860c5976771bca05637ca98ad

CMD ["/bin/bash"]