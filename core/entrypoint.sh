#!/bin/bash
# core/entrypoint.sh
#
# Sprint C — Bootstrap script for Docker deployment.
# Handles LLM model download (idempotent) and starts uvicorn.
#
# Usage:
#   docker run shinttools-core
#   (entrypoint.sh is called automatically)
#
# Environment variables (optional):
#   SHINTTOOLS_MODELS_DIR   — override models directory (default: core/models)
#   SHINTTOOLS_MODEL_FILE   — override model filename
#   SHINTTOOLS_MODEL_URL    — override model download URL
#   SHINTTOOLS_MODEL_SHA256 — override model SHA256 hash
#   UVICORN_HOST            — bind address (default: 0.0.0.0)
#   UVICORN_PORT            — bind port (default: 18200)

set -e  # Exit on first error

echo "=== ShintTools Core Bootstrap ==="
echo "Starting at $(date)"

# Set defaults
: ${UVICORN_HOST:=0.0.0.0}
: ${UVICORN_PORT:=18200}

# Check if agent module is available (Sprint C). The download is gated by
# SHINTTOOLS_AGENT_ENABLED (default off): the LLM agent is an Indie-tier
# feature, and the ~3 GB model would otherwise be pulled for every free
# user too. The launcher sets this env var to "1" via docker-compose
# only when the signed-in account resolves to a paying tier.
if [ -f "modules/agent/model_downloader.py" ]; then
    if [ "$SHINTTOOLS_AGENT_ENABLED" = "1" ]; then
        echo ""
        echo "→ Agent module detected and enabled (Indie tier)"
        echo "→ Checking LLM model..."
        if python -m modules.agent.model_downloader; then
            echo "✓ LLM model ready"
        else
            EXIT_CODE=$?
            if [ $EXIT_CODE -eq 2 ]; then
                echo "⚠ LLM model unavailable (may be offline). Agent endpoints will report 'not available'."
            else
                echo "⚠ Failed to download LLM model (exit code $EXIT_CODE). Agent will gracefully degrade."
            fi
        fi
    else
        echo "→ Agent module present but disabled (SHINTTOOLS_AGENT_ENABLED!=1). LLM agent is an Indie feature; skipping ~3 GB model download."
    fi
else
    echo "→ Agent module not available (main branch only, not develop)"
fi

echo ""
echo "→ Starting uvicorn..."
echo "  Host: $UVICORN_HOST"
echo "  Port: $UVICORN_PORT"
echo ""

# Start the app
exec uvicorn api.main:app \
    --host "$UVICORN_HOST" \
    --port "$UVICORN_PORT"
