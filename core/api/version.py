# Single source of truth for the Core's version string.
# Bumped in lockstep with the git tag that triggers the publish workflow
# (see .github/workflows/publish-core.yml). Imported by both the FastAPI
# app metadata and the /health + /status endpoints so they never drift.

CORE_VERSION = "2.11.1"
