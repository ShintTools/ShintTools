# ShintTools Org Migration — Report

Migrating the legacy owner `Noctxas97Dev` → the `ShintTools` org, and the GHCR
namespace `ghcr.io/noctxas97dev/*` → `ghcr.io/shinttools/*`. Scope: **Core +
Launcher + UE5** (Unity paused per standing rule — flagged below).

> NOTE: this report deliberately cites the legacy values to document the mapping;
> they are not live references.

## Phase 1 — functional references (DONE, committed)

| Old (legacy) | New (org) | File(s) | Status |
|---|---|---|---|
| `ghcr.io/noctxas97dev/shinttools-core` | `ghcr.io/shinttools/shinttools-core` | Core `publish-core.yml` (images + visibility API → `/orgs/ShintTools`) | ✅ `39b2e0a` |
| `ghcr.io/noctxas97dev/shinttools-core(-paid)` | `ghcr.io/shinttools/…` | Launcher `constants.py` (`CORE_IMAGE_REMOTE`/`_PAID`/`_PRIVATE`) | ✅ `258b35f` |
| `ghcr.io/noctxas97dev/shinttools-core:latest` | `ghcr.io/shinttools/…` | UE5 `ShintCoreInstaller.h` (`ImageTag`) | ✅ `af73232` |
| `Noctxas97Dev/ShintTools{,_UE5,_Unity,_Launcher}` | `ShintTools/…` | Launcher `constants.py` `GITHUB_REPO_*`, `installer.py`, `updater.py` | ✅ `258b35f` |
| compose image + UE5 submodule URL | `ShintTools/…` | Core `docker-compose.yml`, `.gitmodules` | ✅ `ab781dd` |
| local git remotes | `https://github.com/ShintTools/…` | 3 working dirs | ✅ repointed |
| Core image republished to org | `ghcr.io/shinttools/shinttools-core(-paid):2.0.8` | `v2.0.8` | ✅ published |

## Phase 2 — docs / tooling sweep (DONE)
READMEs, CHANGELOGs, handoff guides, build scripts (`sync_payload.ps1`,
`build_docs_docx.py`, `run_bug_hunt.ps1`) swept of legacy owner/namespace refs.

### Model repo — migrated (2026-07-01)
- **`ShintTools/ShintTools-Models`** — the model GGUF release repo was
  transferred to the org (legacy `Noctxas97Dev/ShintTools-Models` now 301-redirects;
  the `v2.0-models` release + GGUF asset carried over). `LLM_MODEL_REPO`, the
  compose `SHINTTOOLS_MODEL_URL`, and `model_downloader.py` (launcher + payload +
  Core) repointed to the org. No legacy owner refs remain in functional code.

## Verification
- Launcher unit tests: **41 passing** post-migration.
- **FREE** org image, anonymous pull: ✅ `ghcr.io/shinttools/shinttools-core:latest` + `:2.0.8`.
- **PAID** org image, token pull: ⏳ token mints + `docker login` OK, but **403** —
  the dashboard is still minting from the **user** App installation. Pending: set
  the dashboard's `GH_APP_INSTALLATION_ID` to the **org** installation + grant the
  App **Read** on `ghcr.io/shinttools/shinttools-core-paid` + update the returned
  `image` field to the org namespace.

## Pending — release cutover (gated on the paid pull verifying)
- Launcher: flip `SHINTTOOLS_PAID_PRIVATE` default on, merge `develop`→`main`, release.
- Plugin: merge `develop-paid`→`main`.
- Delete legacy public `:paid`/`*-paid` tags on the old `noctxas97dev` package.

## Out of scope
- **Unity** (`ShintTools_Unity`) — paused per standing rule; same sweep applies when it resumes.
