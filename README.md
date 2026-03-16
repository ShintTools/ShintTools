# ShintTools:
- Ecosistema modular de herramientas de IA Aplicada para Unreal Engine 5 y Unity 6.
- Automatiza validación de código, optimización de assets y QA para estudios de videojuegos.

## Estructura del repositorio

```

shinttools/

├── core/                   # Python Core Engine
│   ├── api/                # Endpoints FastAPI
│   ├── modules/            # Módulos de análisis
│   │   ├── naming/         # Asset Naming Bot
│   │   └── code\_validator/ # Deep Code Validator
│   ├── models/             # Modelos NLP (offline)
│   ├── schemas/            # JSON Schemas (pydantic models)
│   ├── tests/              # pytest
│   ├── Dockerfile
│   └── requirements.txt
├── plugins/
│   ├── unreal/             # UE5 Plugin (C++)
│   └── unity/              # Unity Package (C#)
├── shared/
│   └── schemas/            # JSON Schemas compartidos
├── docs/                   # Documentación y specs
├── scripts/                # Scripts de build y CI
└── .github/workflows/      # GitHub Actions CI

```


## Requisitos previos
- Python 3.11 (gestionado con pyenv)
- Git 2.x+
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

## Pre-commit hooks
Se ejecutan automáticamente antes de cada commit y comprueban la calidad del código Python en `core/`:

Hook -->  Funcion        
- flake8: Revisa errores de estilo y sintaxis 
- black: Formatea el código automáticamente
- isort: Ordena los imports
- mypy: Comprueba tipos de datos



## CI/CD
GitHub Actions ejecuta automáticamente en cada push a `main` y `develop`:

\- `ci-core.yml` — ejecuta pytest sobre el core Python

\- `ci-lint.yml` — ejecuta flake8 + mypy sobre el core



## Ramas
Rama --> Uso 

- main: Código estable. Requiere 2 aprobaciones para merge
- develop: Integración. Requiere 1 aprobación para merge
- feature/ST-XXX-descripcion Trabajo en curso

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
