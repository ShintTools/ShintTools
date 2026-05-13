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

# Compile protected modules → .so, then strip sources so the image ships
# only binaries for proprietary logic. Cython is installed inline and removed
# after compilation to keep the final image lean (~10 MB saved).
# gcc/build-essential are already present for llama-cpp-python.
RUN pip install --no-cache-dir Cython && \
    python setup_cython.py build_ext --inplace && \
    pip uninstall -y Cython && \
    find . -name "*.c" -delete && \
    rm -rf build/cython

# Strip protected .py sources — binary .so files replace them at import time
RUN rm -f \
    modules/code_validator/rules/cpp/cpp_performance.py \
    modules/code_validator/rules/cpp/cpp_best_practices.py \
    modules/code_validator/rules/cpp/cpp_security.py \
    modules/code_validator/rules/cpp/cpp_maintainability.py \
    modules/code_validator/rules/cpp/_cpp_helpers.py \
    modules/code_validator/rules/cpp/ue5_cpp_rules.py \
    modules/code_validator/rules/cpp/cpp_orchestrator.py \
    modules/code_validator/rules/blueprint/blueprint_rules.py \
    modules/code_validator/rules/blueprint/blueprint_orchestrator.py \
    modules/code_validator/rules/_rule_metadata.py \
    modules/code_validator/parsers/cpp_parser.py \
    modules/code_validator/parsers/fixers/fix_patterns.py \
    modules/code_validator/parsers/fixers/cpp_fixer.py \
    modules/code_validator/parsers/cpp_fixer.py \
    modules/code_validator/parsers/fix_patterns.py \
    modules/code_validator/tiers.py \
    modules/metrics/score_calculator.py \
    modules/naming/rules/ue5_naming_rules.py \
    modules/naming/rules/naming_orchestrator.py \
    modules/agent/explainer.py \
    modules/agent/llm_backend.py \
    modules/agent/prefab_explanations.py

# Ensure models directory exists (for LLM agent)
RUN mkdir -p /app/core/models

# Make entrypoint executable
RUN chmod +x entrypoint.sh

EXPOSE 18200

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:18200/health || exit 1

ENTRYPOINT ["bash", "entrypoint.sh"]
