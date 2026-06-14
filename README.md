# ShintTools

Ecosistema modular de herramientas de IA Aplicada para **Unreal Engine 5** y **Unity 6**.
Automatiza validación de código, optimización de assets y QA para estudios de videojuegos.

~197 reglas en 6 categorías · Auto-fix con Tree-sitter · LLM local offline · Quality Score con historial

---

## 🔌 Setup rápido para desarrolladores de plugin

> Si estás desarrollando el **plugin de Unity o UE5** y solo necesitas levantar el Core para testear, sigue estos pasos. **No necesitas saber Python.**

**Requisito único: [Docker Desktop](https://www.docker.com/products/docker-desktop) instalado y ejecutándose.**

```bash
# 1. Clonar el repositorio
git clone https://github.com/Noctxas97Dev/ShintTools.git
cd ShintTools

# 2. Levantar el Core
#    La primera vez tarda ~5 minutos mientras compila las dependencias.
docker compose -f docker-compose.plugin-dev.yml up --build
```

Cuando aparezca `Application startup complete` en los logs, el Core está listo.

**Verificar:** abre `http://localhost:18200/health` en el navegador — debe responder `{"status":"ok",...}`.

El plugin se conecta al Core en **`http://localhost:18200`**.

### Endpoints principales para el plugin de Unity

| Endpoint | Método | Descripción |
|----------|--------|-------------|
| `/health` | GET | Verifica que el Core está activo |
| `/validate/unity/scan` | POST | Analiza scripts C# y devuelve issues + auto-fixes |
| `/assets/unity/scan` | POST | Valida naming de assets contra las reglas Unity |
| `/config` | GET | Lee la configuración activa del Core |

### Detener el Core

```bash
docker compose -f docker-compose.plugin-dev.yml down
```

> El archivo `shinttools.unity.config.json` contiene la configuración de testing (Unity, api_key debug, prefijos) y es montado automáticamente por el compose. No hace falta tocarlo para empezar.

---

## Estructura del repositorio

```
ShintTools/
├── core/                              # Python Core Engine (FastAPI)
│   ├── api/
│   │   ├── main.py                    # App FastAPI + lifespan
│   │   ├── database.py                # Motor (MongoDB async)
│   │   ├── middleware.py              # CORS y middlewares
│   │   └── routes/
│   │       ├── health.py              # GET /health, /ping, /status
│   │       ├── config.py              # GET/POST /config
│   │       ├── validate.py            # POST /validate/*
│   │       ├── unity.py               # POST /validate/unity/scan
│   │       ├── assets.py              # POST /assets/scan, /assets/fix, /assets/unity/scan
│   │       ├── dashboard.py           # POST /dashboard/report
│   │       ├── metrics.py             # GET /metrics/score/*
│   │       ├── agent.py               # POST /agent/plan, /agent/explain
│   │       └── license.py             # POST /license
│   ├── modules/
│   │   ├── code_validator/            # Análisis de código multi-motor
│   │   │   ├── unreal/
│   │   │   │   ├── cpp/               # C++ UE5 (75 reglas: CS/CP/CB/CM)
│   │   │   │   ├── blueprint/         # Blueprint (21 reglas: BPB/BPP/BPM/BPS)
│   │   │   │   └── parsers/           # Tree-sitter fixer C++
│   │   │   ├── unity/
│   │   │   │   ├── csharp/            # C# Unity (57 reglas: CSS/CSP/CSB/CSM/UNI)
│   │   │   │   ├── visual_scripting/  # Visual Scripting (~8 reglas)
│   │   │   │   └── parsers/           # Parser C# + Unity VS
│   │   │   └── shared/                # Tier config, RULE_NAMES registry
│   │   ├── naming/                    # Asset Naming Bot
│   │   │   ├── unreal/                # UE5 naming (NM001-NM018: 18 reglas)
│   │   │   └── unity/                 # Unity naming (NMU001, NMU009, NMU016 + 18 compartidas)
│   │   ├── agent/                     # LLM local (Qwen2.5-Coder 1.5B)
│   │   │   ├── llm_backend.py         # Carga y ejecución del modelo GGUF
│   │   │   ├── explainer.py           # Generación de explicaciones por issue
│   │   │   ├── prefab_explanations.py # Cache de explicaciones Opus 4.7
│   │   │   ├── model_downloader.py    # Descarga del modelo desde GitHub Releases
│   │   │   ├── custom_rule_checker.py # Evaluación de reglas definidas por usuario
│   │   │   └── finetuning_logger.py   # Log JSONL para fine-tuning futuro
│   │   ├── metrics/                   # Quality Score system
│   │   │   └── score_calculator.py    # Cómputo por severidad y categoría
│   │   └── lod_auditor/               # Auditoría de LOD de assets
│   │       ├── rules/                 # lod_textures, lod_meshes, lod_materials
│   │       ├── vram_model.py          # Estimación de VRAM
│   │       └── schema.py              # Modelos Pydantic
│   ├── scripts/                       # Scripts de desarrollo y smoke tests
│   ├── tests/                         # Tests de API (pytest + httpx)
│   ├── Dockerfile
│   ├── requirements.txt
│   └── setup_cython.py                # Compilación Cython de módulos protegidos
├── plugins/
│   └── unreal/                        # UE5 Plugin C++ (git submodule)
│       └── Source/ShintTools/         # Core/, UI/, Utils/
├── data/
│   └── prefabricated_explanations.json  # Cache de explicaciones Opus 4.7 (~158 KB)
├── models/
│   └── Qwen2.5-Coder-1.5B-Instruct-Q4_K_M.gguf  # Modelo LLM local (~940 MB)
├── tools/
│   └── _add_noqa_e501.py
├── .github/workflows/
│   ├── ci-core.yml                    # pytest core/tests/
│   └── ci-lint.yml                    # flake8 + mypy
├── docker-compose.yml                 # Stack completo (con LLM agent)
├── docker-compose.plugin-dev.yml      # Stack para devs de plugin (sin LLM, arranque rápido)
├── shinttools.config.json             # Config de ejemplo (Unreal)
└── shinttools.unity.config.json       # Config de ejemplo (Unity, para plugin-dev)
```

---

## Módulos

### Deep Code Validator

Analiza código de UE5 (C++, Blueprint) y Unity 6 (C#, Visual Scripting). Detecta problemas y genera auto-fixes.

#### Unreal Engine 5 — C++ (75 reglas)

| Categoría | Prefijo | Reglas | Ejemplos |
|-----------|---------|--------|---------|
| Security | CS | CS001–CS017 (15) | GetWorld nullptr, SpawnActor check, bounds check, division by zero |
| Performance | CP | CP001–CP018 (17) | FindObject en Tick, GetComponent en Tick, sleep en game thread |
| Best Practices | CB | CB001–CB035 (34) | raw new/delete, STL en UE5, magic numbers, missing override |
| Maintainability | CM | CM001–CM009 (9) | funciones largas, nesting profundo, TODOs, debug messages |

**Auto-fix engine:** Tree-sitter AST para transformaciones complejas (`move_to_beginplay`, `extract_function`). Genera before/after para aprobación del usuario en el plugin.

#### Unreal Engine 5 — Blueprint (21 reglas)

| Prefijo | Reglas | Descripción |
|---------|--------|-------------|
| BPB | BPB001–BPB007 (7) | Naming de assets, funciones y variables |
| BPP | BPP001–BPP005 (5) | Tick habilitado sin necesidad, cast count, total nodes |
| BPM | BPM001–BPM007 (7) | Variables no usadas, nodos desconectados, complejidad |
| BPS | BPS001, BPS003 (2) | Exposición de datos sensibles en BP |

#### Unity 6 — C# (57 reglas)

| Categoría | Prefijo | Reglas | Ejemplos |
|-----------|---------|--------|---------|
| Security | CSS | CSS001–CSS009 (9) | SQL concat, hardcoded secret, HTTP URL, PlayerPrefs |
| Performance | CSP | CSP001–CSP010 (11) | LINQ en Update, string concat en loop, GC.Collect |
| Best Practices | CSB | CSB001–CSB014 (14) | Empty catch, async void, evento sin unsub, magic number |
| Maintainability | CSM | CSM001–CSM005 (5) | Long method, god object, too many params, deep nesting |
| Unity-Specific | UNI | UNI001–UNI018 (18) | FindObject/GetComponent en Update, Camera.main, Resources.Load |

#### Unity 6 — Visual Scripting (~8 reglas)

Validación de grafos: unit count, ciclos, nodos desconectados.

---

### Asset Naming Bot

Valida convenciones de naming de assets (prefijos, sufijos, PascalCase, folder correcta).

#### Unreal Engine 5 (18 reglas, NM001–NM018)

62 tipos de assets mapeados en 8 categorías: Textures, Meshes, Materials, Blueprints, Widgets, Audio, VFX, Data.

#### Unity 6 (21 conceptos: NMU001, NMU009, NMU016 + 18 compartidas)

17 tipos oficiales con prefijo: `T_` Texture2D, `M_` Material, `O_` GameObject/Prefab,
`A_` AudioClip, `AN_` AnimationClip, `ANC_` AnimationController, `SH_` Shader,
`S_` SceneAsset, entre otros. Tabla completa en
`core/modules/naming/unity/unity_naming_rules.py`.

---

### Agent LLM (Indie-tier)

Explicaciones en lenguaje natural para cada issue detectado. Funciona 100% offline — no sale ningún dato de la máquina del usuario.

- **Modelo:** Qwen2.5-Coder 1.5B Instruct (Q4_K_M GGUF, ~940 MB)
- **Runtime:** llama-cpp-python (CPU, ~20–40 s por explicación en hardware modesto)
- **Cache prefabricada:** ~158 KB de explicaciones generadas con Opus 4.7 para las reglas más comunes — respuesta instantánea sin inferencia LLM
- **Custom rules:** El usuario puede definir sus propias reglas (problema + solución en lenguaje natural) y el modelo las evalúa contra el código
- **Fine-tuning logger:** Cada explicación generada se registra en JSONL para mejorar el modelo en el futuro
- **Activación:** Variable de entorno `SHINTTOOLS_AGENT_ENABLED=1` (solo cuando la licencia Indie está activa)

---

### Quality Score y Métricas

Calcula un score 0–100 a partir de issues detectados por severidad y categoría. Persiste en MongoDB para análisis de tendencias. El score se recalcula automáticamente tras aplicar auto-fixes.

---

### LOD Auditor

Audita las cadenas de LOD de assets: texturas, meshes y materiales. Estima VRAM y genera recomendaciones de optimización por asset.

---

## API Endpoints

El Core Engine expone estos endpoints (FastAPI, puerto `18200`):

### Health & Status

| Endpoint | Método | Descripción |
|----------|--------|-------------|
| `/health` | GET | Health check (incluye commit SHA) |
| `/ping` | GET | Round-trip test |
| `/status` | GET | Estado detallado: versión, módulos, DB, LLM |

### Configuración

| Endpoint | Método | Descripción |
|----------|--------|-------------|
| `/config` | GET | Leer `shinttools.config.json` activo |
| `/config` | POST | Actualizar configuración |

### Validación de Código

| Endpoint | Método | Descripción |
|----------|--------|-------------|
| `/validate/code` | POST | Análisis de un solo archivo C++ |
| `/validate/project` | POST | Scan completo del proyecto (batch, retorna Quality Score) |
| `/validate/blueprints` | POST | Análisis de exportación BP (retorna Quality Score) |
| `/validate/unity-graphs` | POST | Validación de grafos de Visual Scripting |
| `/validate/fix` | POST | Aplicar auto-fixes con Tree-sitter |
| `/validate/unity/scan` | POST | Scan completo C# Unity con fixes inline |

### Assets

| Endpoint | Método | Descripción |
|----------|--------|-------------|
| `/assets/scan` | POST | Detectar violaciones de naming (UE5) |
| `/assets/fix` | POST | Aplicar correcciones de naming (UE5) |
| `/assets/unity/scan` | POST | Scan de naming Unity con reglas built-in + custom |

### Métricas y Dashboard

| Endpoint | Método | Descripción |
|----------|--------|-------------|
| `/metrics/score/latest` | GET | Último Quality Score del proyecto |
| `/metrics/score/history` | GET | Historial de scores (máx. 100 registros) |
| `/dashboard/report` | POST | Sync de reporte completo para el dashboard web |

### Agent LLM (Indie-tier)

| Endpoint | Método | Descripción |
|----------|--------|-------------|
| `/agent/explain` | POST | Explicación en lenguaje natural de un issue |
| `/agent/explain/stream` | POST | Explicación en streaming (SSE) |
| `/agent/plan` | POST | Plan de fixes priorizado (determinístico) |

### Licencia

| Endpoint | Método | Descripción |
|----------|--------|-------------|
| `/license` | POST | Resolver tier de licencia (free / indie) |

---

## Tech Stack

| Capa | Tecnología |
|------|-----------|
| Core Engine | Python 3.11, FastAPI 0.111, Uvicorn 0.30, Pydantic 2.7 |
| Base de datos | MongoDB 6.0 (Motor async, pymongo) |
| Análisis C++ | Tree-sitter 0.21 (`tree-sitter-cpp`) |
| Análisis C# | Parser propio (regex + AST manual) |
| LLM local | llama-cpp-python 0.3.2, Qwen2.5-Coder 1.5B Q4_K_M |
| Compilación | Cython (módulos propietarios → `.so`) |
| Testing | pytest 8.2, httpx 0.27 |
| CI | GitHub Actions (pytest + flake8 + mypy) |

---

## Requisitos previos (desarrollo del core)

- Python 3.11 (gestionado con pyenv)
- Git 2.x+
- MongoDB 6+ (local o via Docker)
- Docker (para levantar el stack completo)

---

## Configuración del entorno local (desarrollo del core)

### 1. Clonar el repositorio

```bash
git clone https://github.com/Noctxas97Dev/ShintTools.git
cd ShintTools
```

### 2. Instalar Python 3.11 con pyenv

```bash
pyenv install 3.11.9
pyenv global 3.11.9
python --version  # Python 3.11.9
```

### 3. Instalar dependencias del core

```bash
# PyTorch CPU necesita su propio index URL
pip install torch==2.3.0+cpu --index-url https://download.pytorch.org/whl/cpu

# El resto de dependencias
pip install -r core/requirements.txt
```

### 4. Instalar y activar pre-commit hooks

```bash
pip install pre-commit flake8 black isort mypy
pre-commit install
```

Verificar que los hooks funcionan:

```bash
pre-commit run --all-files
```

### 5. Levantar MongoDB

```bash
# Con Docker (recomendado)
docker run -d -p 27017:27017 --name shinttools-mongo mongo:6.0

# O local
mongod --dbpath /data/db
```

### 6. Ejecutar el Core Engine en modo desarrollo

```bash
cd core
MONGODB_URL=mongodb://localhost:27017/shinttools uvicorn api.main:app --host 0.0.0.0 --port 18200 --reload
```

---

## Pre-commit hooks

Se ejecutan automáticamente antes de cada commit y comprueban la calidad del código Python en `core/`:

| Hook | Descripción |
|------|-------------|
| `flake8` | Errores de estilo y sintaxis |
| `black` | Formateo automático (line-length 88) |
| `isort` | Ordenación de imports (profile black) |
| `mypy` | Comprobación de tipos |

---

## CI/CD

GitHub Actions se ejecuta en cada push a `main` y `develop`:

| Workflow | Descripción |
|----------|-------------|
| `ci-core.yml` | `pytest core/tests/` con Python 3.11 |
| `ci-lint.yml` | `flake8` + `mypy` sobre `core/` |

---

## Ramas

| Rama | Descripción | Aprobaciones para merge |
|------|-------------|------------------------|
| `main` | Código estable | 2 |
| `develop` | Integración | 1 |
| `feature/ST-XXX-descripcion` | Trabajo en curso | — |

---

## Docker

### Stack completo (con LLM Agent)

```bash
docker compose up --build
```

Incluye MongoDB + Core + descarga del modelo Qwen2.5-Coder 1.5B (~940 MB la primera vez).

### Stack para desarrolladores de plugin (sin LLM, arranque rápido)

```bash
docker compose -f docker-compose.plugin-dev.yml up --build
```

Sin descarga de modelo. El Core arranca en ~2 minutos.

---

## Configuración

El Core busca `shinttools.config.json` automáticamente (hasta 5 niveles de directorio padre desde `core/api/main.py`).

**Ejemplo para Unreal Engine 5** (`shinttools.config.json`):

```json
{
  "project_name": "MyGame",
  "engine": "unreal",
  "core_port": 18200,
  "modules": {
    "naming": { "enabled": true },
    "code_validator": { "enabled": true }
  },
  "naming": {
    "textures": { "prefix": "T_", "case": "PascalCase" },
    "meshes": { "prefix": "SM_", "case": "PascalCase" }
  },
  "code_validator": {
    "max_cyclomatic_complexity": 15,
    "max_file_lines": 500,
    "exclude_paths": ["Content/ThirdParty/", "Plugins/"]
  }
}
```

**Para Unity 6**, usa `shinttools.unity.config.json` como referencia (prefijos Unity, `"engine": "unity"`).

---

## Tiers de licencia

| Tier | Acceso |
|------|--------|
| Free | Subconjunto de reglas built-in, sin LLM agent |
| Indie | Todas las reglas, LLM agent (explicaciones + custom rules), Quality Score history |
