# ShintTools — Context for Claude Code

## Qué es ShintTools

SaaS de análisis estático para Unreal Engine 5. Detecta problemas de
rendimiento, seguridad, buenas prácticas, mantenibilidad y nomenclatura
en código C++, Blueprints y assets. Tiene un plugin de UE5 que envía
el código al backend (FastAPI), recibe issues, y ofrece auto-fix con
Tree-sitter.

## Equipo

- **Genesis** — Backend, reglas de análisis, módulos Python, API.
- **Raúl** — Plugin UE5 (C++/Slate), dashboard, Launcher.

## Estructura del proyecto

```
ShintTools/
├── core/                          # Backend Python (FastAPI)
│   ├── api/
│   │   ├── main.py                # App entry point, lifespan, routers
│   │   ├── database.py            # MongoDB async (motor): analysis_results, licenses, project_scores
│   │   ├── middleware.py           # CORS, rate limiting
│   │   └── routes/
│   │       ├── validate.py        # POST /validate/code|project|blueprints|fix|assets
│   │       ├── metrics.py         # GET /metrics/score/latest|history
│   │       ├── assets.py          # POST /assets/scan|fix
│   │       ├── dashboard.py       # POST /dashboard/report
│   │       ├── agent.py           # POST /agent/plan (Indie-only)
│   │       ├── health.py          # GET /health|ping|status
│   │       └── config.py          # GET/POST /config
│   ├── modules/
│   │   ├── code_validator/
│   │   │   ├── rules/cpp/         # 75 reglas C++ (CP, CS, CB, CM)
│   │   │   ├── rules/blueprint_rules.py  # 21 reglas Blueprint (BPP, BPS, BPB, BPM)
│   │   │   ├── parsers/           # Tree-sitter fixer (cpp_fixer.py, fix_patterns.py)
│   │   │   ├── tiers.py           # Free (40 reglas) vs Indie (114 reglas)
│   │   │   └── tests/
│   │   ├── metrics/
│   │   │   ├── score_calculator.py  # Quality Score: 0-100, penalty-based
│   │   │   └── tests/
│   │   └── naming/
│   │       └── rules/ue5_naming_rules.py  # 18 reglas de nomenclatura (NM)
│   ├── tests/                     # Integration tests (health, config, validate)
│   └── schemas/
├── plugins/
│   ├── unreal/                    # Plugin UE5 C++ (Raúl)
│   └── unity/                     # Placeholder
├── shared/schemas/                # JSON schemas
├── docs/
└── scripts/
```

## Quality Score (Sprint B — completado)

Fórmula: `score = max(0, 100 - penalty / max(files_scanned, 1))`

Pesos por severidad: error = 5, warning = 2, info = 0.5.
Las reglas NM (naming) tienen peso reducido ×0.5 porque no afectan runtime.

Sub-scores por categoría:
- Performance: CP + BPP
- Security: CS + BPS
- Best Practices: CB + BPB
- Maintainability: CM + BPM
- Naming: NM

El score se calcula automáticamente después de /validate/project,
/validate/blueprints, y /validate/fix (sin re-escanear).

## Tiers

- **Free**: 40 reglas (30 C++ + 10 BP), assets limitados a 500.
- **Indie**: 114 reglas (75 C++ + 21 BP + 18 NM), assets ilimitados, /agent/plan.

El tier se resuelve por api_key → MongoDB collection `licenses`.

## Roadmap

- Sprint A — ShintLive (watcher + /validate/incremental). DONE (Raúl).
- Sprint B — Quality Score. DONE.
- Sprint C — Agente LLM: llama_cpp backend (DeepSeek Coder 6.7B), POST /agent/review SSE.
- Sprint D — POST /agent/explain-fix con SSE.
- Sprint E — BP Heat Map: overlay de complejidad en el graph editor.

## Convenciones de código

- Python 3.10+, FastAPI, motor (async MongoDB).
- Formateo: black (88 chars), isort (profile=black), flake8.
- Pre-commit hooks configurados. Todas las reglas en pyproject.toml.
- Tests: pytest. Correr desde core/: `python -m pytest`
- Branch principal de desarrollo: `develop`.
- Idioma de comunicación: español.

## Notas importantes

- No tocar plugins/unreal/ — ese código es de Raúl.
- Los tests test_cm006_cp003.py y test_tree_sitter.py tienen errores
  pre-existentes de Tree-sitter (no bloquean el resto de la suite).
- El dashboard actual muestra "Puntuación de Optimización" que es el
  Quality Score que calculamos en el backend.
