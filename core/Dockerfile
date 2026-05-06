FROM python:3.11-slim-bookworm

WORKDIR /app/core

# gcc is required by Cython to compile .py -> .so
# libgomp1 required at runtime for OpenMP (needed by llama-cpp-python)
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc build-essential libgomp1 && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# torch needs a separate index for the CPU-only wheel
RUN pip install --no-cache-dir torch==2.3.0+cpu --index-url https://download.pytorch.org/whl/cpu

# Install all remaining dependencies from requirements.txt
# Compile llama-cpp-python locally for glibc compatibility (not prebuilt wheel)
RUN pip install --no-cache-dir -r requirements.txt --no-binary llama-cpp-python

COPY . .

# Sprint C (LLM agent) runs pure Python — no Cython compilation needed
# Keep gcc/build-essential for llama-cpp-python runtime (libgomp.so.1)
# (Cython compilation disabled for stability; code works fine in pure Python)

# Sprint C — ensure models directory exists (for LLM agent)
RUN mkdir -p /app/core/models

# Make entrypoint executable
RUN chmod +x entrypoint.sh

EXPOSE 18200

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:18200/health || exit 1

ENTRYPOINT ["bash", "entrypoint.sh"]
