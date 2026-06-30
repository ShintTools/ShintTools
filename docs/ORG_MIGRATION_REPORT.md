# ShintTools Org Migration — Report

Migrating `Noctxas97Dev/*` → `ShintTools/*` (org) and the GHCR namespace
`ghcr.io/noctxas97dev/*` → `ghcr.io/shinttools/*`. Scope: **Core + Launcher +
UE5** (Unity paused per standing rule — flagged below).

## Phase 1 — functional references (DONE, committed)

| Old reference | New reference | File(s) | Status |
|---|---|---|---|
| `ghcr.io/noctxas97dev/shinttools-core` | `ghcr.io/shinttools/shinttools-core` | Core `publish-core.yml` (images + visibility API → `/orgs/ShintTools`) | ✅ committed `39b2e0a` |
| `ghcr.io/noctxas97dev/shinttools-core(-paid)` | `ghcr.io/shinttools/…` | Launcher `constants.py` (`CORE_IMAGE_REMOTE`/`_PAID`/`_PRIVATE`) | ✅ `258b35f` |
| `ghcr.io/noctxas97dev/shinttools-core:latest` | `ghcr.io/shinttools/…` | UE5 `ShintCoreInstaller.h` (`ImageTag`) | ✅ `af73232` |
| `Noctxas97Dev/ShintTools{,_UE5,_Unity,_Launcher}` | `ShintTools/…` | Launcher `constants.py` `GITHUB_REPO_*`, `installer.py`, `updater.py` | ✅ `258b35f` |
| `Noctxas97Dev/ShintTools` (compose image + submodule) | `ShintTools/…` | Core `docker-compose.yml`, `.gitmodules` | ✅ `ab781dd` |
| local git remotes | `https://github.com/ShintTools/…` | 3 working dirs | ✅ repointed |
| Core image republished | `ghcr.io/shinttools/shinttools-core(-paid):2.0.8` | `v2.0.8` tag | ⏳ publishing |

### Intentionally NOT migrated
- **`Noctxas97Dev/ShintTools-Models`** — the model GGUF release repo is **not**
  under the org (org `/ShintTools-Models` 404s). `LLM_MODEL_REPO`, the compose
  `SHINTTOOLS_MODEL_URL`, and `model_downloader.py` keep the user reference.
  *Action item: migrate that repo to the org too, then flip these refs.*

## Pending — user (GitHub side)
1. **Install the GitHub App "ShintTools Core" on the `ShintTools` org** (flip the
   App to "Any account" or transfer it to the org), then update the dashboard
   secret `GH_APP_INSTALLATION_ID` to the **org** installation. *Required before
   the paid `shinttools-core-paid` pull can authenticate.*
2. After `v2.0.8` publishes: confirm `ghcr.io/shinttools/shinttools-core` is
   **public** and `…-core-paid` is **private**, and grant the App **Read** on the
   paid package.

## Pending — code (Phase 2, not yet done)
- **Docs/README/CHANGELOG link sweep** (Core, Launcher, UE5): handoff guides,
  badges, READMEs still cite `Noctxas97Dev`. Non-functional; cosmetic + broken-link.
- **Build tooling**: `scripts/sync_payload.ps1`, `tools/build_docs_docx.py`,
  `tools/bug_hunt/run_bug_hunt.ps1` — audit repo refs.
- **Release cutover** (gated on verification): flip launcher
  `SHINTTOOLS_PAID_PRIVATE` default → on, merge launcher `develop`→`main` + release,
  merge plugin `develop-paid`→`main`, delete legacy public `:paid` tags on the old
  `noctxas97dev` package.
- **Unity** (`ShintTools_Unity`): excluded per the standing "Unity paused" rule —
  references there still need the same sweep when that repo resumes.

## Verification status
- Launcher unit tests: **41 passing** post-migration.
- Free org image pull (anonymous): pending `v2.0.8` publish.
- Paid org image pull (token): pending the App-on-org step above.
