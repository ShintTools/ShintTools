# ShintTools

Modular Applied AI tools ecosystem for **Unreal Engine 5** and **Unity 6**.
Automates code validation, asset optimization, and QA for game studios.

~197 rules across 6 categories · Tree-sitter auto-fix · Local offline LLM · Quality Score with history

---

## Quick Setup for Plugin Developers

> If you are developing the **Unity or UE5 plugin** and only need to start the Core for testing, follow these steps. **You do not need to know Python.**

**Only requirement: Docker Desktop installed and running.**

```bash
git clone https://github.com/ShintTools/ShintTools.git
cd ShintTools
docker compose -f docker-compose.plugin-dev.yml up --build
```

When `Application startup complete` appears in the logs, the Core is ready.

**Check:** open `http://localhost:18200/health` in your browser. It should return `{"status":"ok",...}`.

The plugin connects to **http://localhost:18200**.

### Main Unity Plugin Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Verify the Core is running |
| `/validate/unity/scan` | POST | Analyze C# scripts and return issues + auto-fixes |
| `/assets/unity/scan` | POST | Validate asset naming against Unity rules |
| `/config` | GET | Read the active Core configuration |

### Stop the Core

```bash
docker compose -f docker-compose.plugin-dev.yml down
```

---

## Repository Structure

The repository contains:
- Python Core Engine (FastAPI)
- Multi-engine code validation modules
- Asset Naming Bot
- Local LLM Agent (Qwen2.5-Coder 1.5B)
- Quality Score system
- LOD Auditor
- Unreal Engine plugin
- CI/CD workflows and Docker environments

---

## Modules

### Deep Code Validator

Analyzes UE5 (C++, Blueprint) and Unity 6 (C#, Visual Scripting) code.
Detects issues and generates auto-fixes.

#### Unreal Engine 5 — C++ (75 rules)

Categories:
- Security (CS)
- Performance (CP)
- Best Practices (CB)
- Maintainability (CM)

Examples include null checks, SpawnActor validation, avoiding expensive calls in Tick, raw new/delete detection, missing overrides, deep nesting, and more.

#### Unreal Engine 5 — Blueprint (21 rules)

Validation of:
- Asset, function, and variable naming
- Tick usage
- Cast count and node complexity
- Unused variables
- Disconnected nodes
- Sensitive data exposure

#### Unity 6 — C# (57 rules)

Categories:
- Security (CSS)
- Performance (CSP)
- Best Practices (CSB)
- Maintainability (CSM)
- Unity-Specific (UNI)

Examples include SQL concatenation, hardcoded secrets, LINQ in Update, GC.Collect usage, async void, event unsubscription, Camera.main misuse, Resources.Load, and more.

#### Unity 6 — Visual Scripting

Graph validation including:
- Unit count
- Cycles
- Disconnected nodes

---

### Asset Naming Bot

Validates naming conventions for assets, including prefixes, suffixes, PascalCase usage, and folder placement.

#### Unreal Engine 5

18 rules (NM001–NM018) covering 62 asset types in 8 categories.

#### Unity 6

Supports official asset prefixes such as:
- T_ (Texture2D)
- M_ (Material)
- O_ (GameObject/Prefab)
- A_ (AudioClip)
- AN_ (AnimationClip)
- ANC_ (AnimationController)
- SH_ (Shader)
- S_ (SceneAsset)

---

### LLM Agent (Indie Tier)

Natural-language explanations for detected issues.

- Model: Qwen2.5-Coder 1.5B Instruct (GGUF)
- Runtime: llama-cpp-python
- Offline operation: no user data leaves the machine
- Prefabricated explanation cache for instant responses
- Custom user-defined rules
- Fine-tuning logging for future model improvements

Activation:

```text
SHINTTOOLS_AGENT_ENABLED=1
```

---

### Quality Score and Metrics

Calculates a score from 0–100 based on detected issues, severity, and category.
Stores historical data in MongoDB and automatically recalculates after fixes are applied.

---

### LOD Auditor

Audits LOD chains for:
- Textures
- Meshes
- Materials

Provides VRAM estimates and optimization recommendations.

---

## API Endpoints

### Health & Status

- GET /health
- GET /ping
- GET /status

### Configuration

- GET /config
- POST /config

### Code Validation

- POST /validate/code
- POST /validate/project
- POST /validate/blueprints
- POST /validate/unity-graphs
- POST /validate/fix
- POST /validate/unity/scan

### Assets

- POST /assets/scan
- POST /assets/fix
- POST /assets/unity/scan

### Metrics & Dashboard

- GET /metrics/score/latest
- GET /metrics/score/history
- POST /dashboard/report

### LLM Agent

- POST /agent/explain
- POST /agent/explain/stream
- POST /agent/plan

### Licensing

- POST /license

---

## Tech Stack

- Python 3.11
- FastAPI
- Uvicorn
- Pydantic
- MongoDB
- Tree-sitter
- llama-cpp-python
- Qwen2.5-Coder
- Cython
- pytest
- GitHub Actions

---

## Development Requirements

- Python 3.11
- Git 2.x+
- MongoDB 6+
- Docker

---

## Local Development Setup

1. Clone the repository.
2. Install Python 3.11 with pyenv.
3. Install dependencies.
4. Install pre-commit hooks.
5. Start MongoDB.
6. Run the Core Engine with Uvicorn.

---

## CI/CD

GitHub Actions workflows:
- ci-core.yml
- ci-lint.yml

---

## Branches

- main: Stable code
- develop: Integration branch
- feature/ST-XXX-description: Feature work

---

## Docker

### Full Stack

```bash
docker compose up --build
```

Includes MongoDB, Core, and automatic Qwen model download.

### Plugin Developer Stack

```bash
docker compose -f docker-compose.plugin-dev.yml up --build
```

Fast startup without the LLM model download.

---

## Configuration

The Core automatically searches for `shinttools.config.json`.

Example configuration includes:
- Project name
- Engine type (Unreal or Unity)
- Enabled modules
- Naming rules
- Code validator limits and exclusions

---

## License Tiers

| Tier | Access |
|------|--------|
| Free | Subset of built-in rules, no LLM Agent |
| Indie | All rules, LLM Agent, custom rules, Quality Score history |
| Studio | All rules, LLM Agent, custom rules, Quality Score history + LOD + Predictive |
