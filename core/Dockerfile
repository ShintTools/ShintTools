FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .

# torch needs a separate index for the CPU-only wheel
RUN pip install --no-cache-dir torch==2.3.0+cpu --index-url https://download.pytorch.org/whl/cpu

# Install all remaining dependencies from requirements.txt
# (torch is already installed above, pip will skip it)
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# ── Cython source-protection step intentionally REMOVED ───────────────────
# The previous Dockerfile compiled rule modules to .so via Cython and then
# deleted the original .py source — but anyone cloning the repo to build
# already has the unencrypted source on disk, so the "protection" only
# applied to the contents of the running container. In return it was a
# frequent build-failure source: gcc unavailable, Cython codegen errors,
# missing/renamed modules in the file list, or `pip uninstall -y Cython`
# leaving the image in a broken state.
#
# If genuine source protection is needed in the future, ship a
# pre-compiled wheel from CI rather than compiling at image build time.

EXPOSE 18200

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:18200/health || exit 1

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "18200"]
