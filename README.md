# ShintTools

Ecosistema modular de herramientas de IA Aplicada para Unreal Engine 5 y Unity 6.
Automatiza validación de código, optimización de assets y QA para estudios de videojuegos.

## Estructura del repositorio

```
shinttools/
├── core/                          # Python Core Engine (FastAPI)
│   ├── api/
│   │   ├── main.py                # App FastAPI + lifespan
│   │   ├── database.py            # Motor (MongoDB async)
│   │   ├── middleware.py           # CORS y middlewares
│   │   └── routes/
│   │       ├── health.py          # GET /health, /ping, /status
│   │       ├── config.py          # GET/POST /config
│   │       ├── validate.py        # POST /validate/*
│   │       ├── assets.py          # POST /assets/scan, /assets/fix
│   │       └── dashboard.py       # POST /dashboard/report
│   ├── modules/
│   │   ├── code_validator/        # Deep Code Validator
│   │   │   ├── parsers/
│   │   │   │   ├── cpp_parser.py      # Tree-sitter C++ AST parser
│   │   │   │   ├── cpp_fixer.py       # Auto-fix engine (28 patterns)
│   │   │   │   └── fix_patterns.py    # Rule → Pattern mapping
│   │   │   ├── rules/
│   │   │   │   ├── cpp/
│   │   │   │   │   ├── ue5_cpp_rules.py       # Runner (64 reglas)
│   │   │   │   │   ├── cpp_performance.py     # CP001-CP016
│   │   │   │   │   ├── cpp_best_practices.py  # CB001-CB032
│   │   │   │   │   ├── cpp_security.py        # CS001-CS012
│   │   │   │   │   ├── cpp_maintainability.py # CM001-CM008
│   │   │   │   │   └── _cpp_helpers.py        # Helpers compartidos
│   │   │   │   └── blueprint_rules.py         # BPB/BPP/BPM (6 reglas)
│   │   │   └── tests/                 # Tests del validator
│   │   └── naming/                # Asset Naming Bot
│   │       └── rules/
│   │           └── ue5_naming_rules.py  # 62 tipos → 8 categorías
│   ├── models/                    # Modelos NLP (Sprint 4)
│   ├── schemas/                   # Pydantic models
│   ├── tests/                     # Tests de API (pytest)
│   ├── Dockerfile
│   ├── requirements.txt
│   └── requirements-ci.txt
├── plugins/
│   ├── unreal/                    # UE5 Plugin (C++)
│   └── unity/                     # Unity Package (C#)
├── shared/
│   └── schemas/                   # JSON Schemas compartidos
├── docs/                          # Documentación y specs
├── scripts/                       # Scripts de build y CI
├── shinttools.config.json         # Configuración del proyecto
└── .github/workflows/             # GitHub Actions CI
```

## Módulos

### Deep Code Validator

Analiza código C++ de UE5 y exportaciones de Blueprints. Detecta problemas y genera auto-fixes con Tree-sitter.

**Reglas C++ (64 reglas en 4 categorías):**

- **Performance (CP):** 15 reglas — llamadas costosas en Tick, allocations en loops, FORCEINLINE, sleep en game thread
- **Best Practices (CB):** 31 reglas — raw new/delete, STL en UE5, magic numbers, missing override/Super::BeginPlay, lambda captures
- **Security (CS):** 10 reglas — null checks (GetWorld, Cast, SpawnActor), bounds checks, division by zero, hardcoded secrets
- **Maintainability (CM):** 8 reglas — funciones largas, nesting profundo, TODOs, debug messages, duplicated includes

**Reglas Blueprint (6 reglas):**

- **BPB:** Naming de assets y variables
- **BPP:** Tick habilitado sin necesidad
- **BPM:** Variables no usadas, nodos desconectados

**Auto-fix engine:** 28 pattern handlers en `cpp_fixer.py`. Usa Tree-sitter AST para transformaciones complejas (move_to_beginplay, extract_function) y regex para el resto. Genera before/after para aprobación del usuario en el plugin.

### Asset Naming Bot

Valida convenciones de naming de assets UE5 (prefijos, sufijos, PascalCase).

**8 categorías:** Textures, Meshes, Materials, Blueprints, Widgets, Audio, VFX, Data.

62 tipos de assets mapeados. No existe categoría "Other" — tipos desconocidos van a "Data" por defecto.

## API Endpoints

El Core Engine expone estos endpoints (FastAPI, puerto `18200`):

| Endpoint | Método | Descripción |
|----------|--------|-------------|
| `/health` | GET | Health check para plugins |
| `/ping` | GET | Round-trip test |
| `/status` | GET | Estado detallado para dashboard |
| `/config` | GET/POST | Leer/escribir configuración |
| `/validate/code` | POST | Análisis de un solo archivo C++ |
| `/validate/project` | POST | Scan completo del proyecto (batch) |
| `/validate/blueprints` | POST | Análisis de exportación BP del plugin |
| `/validate/fix` | POST | Aplicar auto-fixes con Tree-sitter |
| `/assets/scan` | POST | Detectar violaciones de naming |
| `/assets/fix` | POST | Aplicar correcciones de naming |
| `/dashboard/report` | POST | Sync de reporte para dashboard web |

## Tech Stack

- **Core Engine:** Python 3.11, FastAPI, Pydantic
- **Base de datos:** MongoDB (Motor async, pymongo)
- **Análisis C++:** Tree-sitter (`tree-sitter-cpp`)
- **NLP:** PyTorch, Transformers (Sprint 4)
- **CV:** OpenCV headless (Sprint 4)
- **Testing:** pytest, httpx
- **CI:** GitHub Actions (pytest + flake8 + mypy)

## Requisitos previos

- Python 3.11 (gestionado con pyenv)
- Git 2.x+
- MongoDB 6+ (local o Atlas)
- Docker (para levantar el Core Engine)

## Configuración del entorno local

### 1. Clonar el repositorio
```bash
git clone https://github.com/Genesishg1509/ShintTools.git
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
# Local
mongod --dbpath /data/db

# O con Docker
docker run -d -p 27017:27017 --name shinttools-mongo mongo:7
```

### 6. Ejecutar el Core Engine (desarrollo)
```bash
cd core
uvicorn api.main:app --host 0.0.0.0 --port 18200 --reload
```

## Pre-commit hooks

Se ejecutan automáticamente antes de cada commit y comprueban la calidad del código Python en `core/`:

- **flake8:** Revisa errores de estilo y sintaxis
- **black:** Formatea el código automáticamente
- **isort:** Ordena los imports
- **mypy:** Comprueba tipos de datos

## CI/CD

GitHub Actions ejecuta automáticamente en cada push a `main` y `develop`:

- `ci-core.yml` — ejecuta pytest sobre el core Python
- `ci-lint.yml` — ejecuta flake8 + mypy sobre el core

## Ramas

- **main:** Código estable. Requiere 2 aprobaciones para merge.
- **develop:** Integración. Requiere 1 aprobación para merge.
- **feature/ST-XXX-descripcion:** Trabajo en curso.

## Docker

### Construir la imagen del Core Engine
```bash
docker build -t shinttools-core .
```

### Ejecutar el Core Engine
```bash
docker run -p 18200:18200 shinttools-core
```

El Core Engine arranca en `localhost:18200`.

## Configuración

El archivo `shinttools.config.json` en la raíz del proyecto controla el comportamiento del Core Engine:

```json
{
  "project_name": "MyGame",
  "engine": "unreal",
  "core_port": 18200,
  "modules": {
    "naming": { "enabled": true },
    "code_validator": { "enabled": true }
  }
}
```

El servidor busca este archivo automáticamente al arrancar (hasta 5 niveles de directorio padre).
