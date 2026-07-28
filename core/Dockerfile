FROM python:3.11-slim-bookworm

WORKDIR /app/core

# gcc/build-essential required by Cython and llama-cpp-python
# libgomp1 required at runtime for OpenMP (llama-cpp-python)
# curl required for healthcheck
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc build-essential libgomp1 curl && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# torch needs a separate index for the CPU-only wheel
RUN pip install --no-cache-dir torch==2.3.0+cpu --index-url https://download.pytorch.org/whl/cpu

# Install all remaining dependencies from requirements.txt
# Compile llama-cpp-python locally for glibc compatibility (not prebuilt wheel).
#
# GGML_NATIVE=OFF is CRITICAL for a distributed image. Without it, ggml compiles
# with -march=native for the BUILD machine — and the CI runner that publishes
# this image has AVX-512. The resulting binary then raises SIGILL (illegal
# instruction, container exit 132) the moment it initialises the model context
# on any customer CPU that lacks those instructions — e.g. every AMD Zen 1-3
# chip (Ryzen 5900X etc.), which has no AVX-512. That surfaces to the plugin as
# curl error 52 (empty reply) because the Core never finishes startup.
# OFF builds a portable binary with runtime CPU-feature dispatch (AVX/AVX2/FMA
# selected at load time), so the LLM agent runs on any x86-64 customer machine.
RUN CMAKE_ARGS="-DGGML_NATIVE=OFF -DLLAMA_NATIVE=OFF" \
    pip install --no-cache-dir -r requirements.txt --no-binary llama-cpp-python

COPY . .

# Compile protected modules -> .so, then strip sources so the image ships
# only binaries for proprietary logic. Cython is installed inline and removed
# after compilation to keep the final image lean.
RUN pip install --no-cache-dir Cython && \
    python setup_cython.py build_ext --inplace && \
    pip uninstall -y Cython && \
    find . -name "*.c" -delete && \
    rm -rf build/cython

# Strip protected .py sources - binary .so files replace them at import time
RUN rm -f \
    modules/code_validator/unreal/cpp/cpp_performance.py \
    modules/code_validator/unreal/cpp/cpp_best_practices.py \
    modules/code_validator/unreal/cpp/cpp_security.py \
    modules/code_validator/unreal/cpp/cpp_maintainability.py \
    modules/code_validator/unreal/cpp/_cpp_helpers.py \
    modules/code_validator/unreal/cpp/ue5_cpp_rules.py \
    modules/code_validator/unreal/cpp/cpp_orchestrator.py \
    modules/code_validator/unreal/blueprint/blueprint_rules.py \
    modules/code_validator/unreal/blueprint/blueprint_orchestrator.py \
    modules/code_validator/unity/csharp/csharp_best_practices.py \
    modules/code_validator/unity/csharp/csharp_maintainability.py \
    modules/code_validator/unity/csharp/csharp_performance.py \
    modules/code_validator/unity/csharp/csharp_security.py \
    modules/code_validator/unity/csharp/csharp_orchestrator.py \
    modules/code_validator/unity/csharp/_csharp_helpers.py \
    modules/code_validator/unity/visual_scripting/unity_graph_rules.py \
    modules/code_validator/unity/visual_scripting/unity_graph_orchestrator.py \
    modules/code_validator/unity/parsers/unity_vs_parser.py \
    modules/code_validator/unity/parsers/csharp_parser.py \
    modules/code_validator/shared/_rule_metadata.py \
    modules/code_validator/shared/tiers.py \
    modules/code_validator/unreal/parsers/fixers/fix_patterns.py \
    modules/code_validator/unreal/parsers/fixers/cpp_fixer.py \
    modules/metrics/score_calculator.py \
    modules/naming/unreal/ue5_naming_rules.py \
    modules/naming/unity/unity_naming_rules.py \
    modules/naming/naming_orchestrator.py \
    modules/agent/explainer.py \
    modules/agent/llm_backend.py \
    modules/agent/prefab_explanations.py

# ── Image edition gate ────────────────────────────────────────────────────────
# Two published editions share this Dockerfile, selected at build time:
#   free  (default) — the Fab / free-tier image. The paid sources (LLM agent,
#                     LOD Auditor, dashboard upload) are PHYSICALLY removed so
#                     the restriction can't be lifted at runtime — even
#                     `docker run -e SHINT_CORE_EDITION=paid` finds nothing to
#                     import (api/main.py guards the import and falls back).
#   paid            — Indie + Studio image; keeps the paid modules.
# Built with: docker build --build-arg SHINT_CORE_EDITION=paid ...
ARG SHINT_CORE_EDITION=free
ENV SHINT_CORE_EDITION=${SHINT_CORE_EDITION}
RUN if [ "$SHINT_CORE_EDITION" != "paid" ]; then \
        echo "Building FREE edition — stripping paid modules" && \
        rm -rf modules/agent modules/lod_auditor modules/predictive \
               api/routes/agent.py api/routes/lod_audit.py \
               api/routes/dashboard.py api/routes/predictive.py ; \
    else \
        echo "Building PAID edition — agent + LOD Auditor + dashboard + predictive kept" ; \
    fi

# Normalise entrypoint line endings before use. The repo stores it as LF, but a
# build from a Windows working copy (no .gitattributes) can carry CRLF, which
# makes bash choke on $'\r' and the container exit 127 in a boot loop. Stripping
# CR here is a no-op on CI (already LF) and bulletproofs local Windows builds.
RUN sed -i 's/\r$//' entrypoint.sh && mkdir -p /app/core/models && chmod +x entrypoint.sh

EXPOSE 18200

# start-period=60s — matches the marketplace UE5 wizard timeout. The
# lifespan itself is fast (LLM model load runs in a background task,
# see api/main.py::_load_llm_in_background), so 60s is a generous
# margin for Mongo ping + module detection on slow hardware.
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
  CMD curl -f http://localhost:18200/health || exit 1

ENTRYPOINT ["bash", "entrypoint.sh"]
