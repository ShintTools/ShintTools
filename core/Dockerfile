FROM python:3.11-slim-bookworm

WORKDIR /app/core

# gcc is required by Cython to compile .py -> .so
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc build-essential && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# torch needs a separate index for the CPU-only wheel
RUN pip install --no-cache-dir torch==2.3.0+cpu --index-url https://download.pytorch.org/whl/cpu

# Install all remaining dependencies from requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Cython is only needed at build time, not at runtime
RUN pip install --no-cache-dir Cython setuptools

COPY . .

# ── Cython: compile protected modules to .so binaries ──
# 1. Compile .py -> .so (binary, not readable)
# 2. Delete original .py source files
# 3. Delete .c intermediates and build artifacts
# 4. Remove Cython (not needed at runtime)
RUN python setup_cython.py build_ext --inplace && \
    python -c "\
import os; \
files = [ \
    'modules/code_validator/parsers/cpp_fixer.py', \
    'modules/code_validator/parsers/cpp_parser.py', \
    'modules/code_validator/parsers/fix_patterns.py', \
    'modules/code_validator/rules/cpp/_cpp_helpers.py', \
    'modules/code_validator/rules/cpp/cpp_best_practices.py', \
    'modules/code_validator/rules/cpp/cpp_maintainability.py', \
    'modules/code_validator/rules/cpp/cpp_performance.py', \
    'modules/code_validator/rules/cpp/cpp_security.py', \
    'modules/code_validator/rules/cpp/ue5_cpp_rules.py', \
    'modules/code_validator/rules/blueprint_rules.py', \
    'modules/code_validator/tiers.py', \
    'modules/naming/rules/ue5_naming_rules.py', \
]; \
[os.remove(f) for f in files if os.path.exists(f)]; \
[os.remove(f.replace('.py','.c')) for f in files if os.path.exists(f.replace('.py','.c'))]; \
" && \
    find /app/modules -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null; \
    rm -rf build/ setup_cython.py && \
    pip uninstall -y Cython && \
    apt-get purge -y gcc build-essential && \
    apt-get autoremove -y

# Sprint C — ensure models directory exists (for LLM agent)
RUN mkdir -p /app/core/models

# Make entrypoint executable
RUN chmod +x entrypoint.sh

EXPOSE 18200

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:18200/health || exit 1

ENTRYPOINT ["bash", "entrypoint.sh"]
