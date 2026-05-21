# Testing DeepSeek vs Qwen2.5-Coder Models

Ambos modelos están descargados y separados en carpetas distintas. Los prompts se configuran automáticamente según el modelo cargado.

## 📁 Estructura

```
core/models/
├── deepseek-coder-1.3b-instruct.Q4_K_M.gguf     (0.81 GB) ← DeepSeek
└── agent/
    └── qwen2.5-coder-1.5b/
        └── Qwen2.5-Coder-1.5B-Instruct-Q4_K_M.gguf  (0.92 GB) ← Qwen
```

## 🧪 Pruebas

### Comparar ambos modelos (recomendado)

```bash
python core/scripts/test_both_models.py
```

Esto genera explicaciones con el mismo issue de ejemplo y muestra ambas respuestas para comparar.

### Probar un modelo específico

```bash
# Solo DeepSeek
python core/scripts/test_both_models.py deepseek

# Solo Qwen
python core/scripts/test_both_models.py qwen
```

## 🎯 Qué buscar en las pruebas

| Criterio | Qué revisar |
|----------|-------------|
| **Naturalidad** | ¿Lee conversacional o robótico? |
| **Alucinaciones** | ¿Inventa APIs que no están en la explicación? |
| **Formato** | ¿Menciona el **rule_name** en bold? |
| **Longitud** | ¿Respeta 2-4 oraciones sin listas? |
| **Velocidad** | ¿Genera en <20 segundos en CPU? |
| **Grounding** | ¿Todas las claims vienen de la explicación dada? |

## 🗑️ Descartar un modelo

Si decides que uno no funciona bien:

```bash
# Borrar Qwen (mantener DeepSeek)
rm -r models/agent/qwen2.5-coder-1.5b/
```

O:

```powershell
# En PowerShell
Remove-Item -Path "models/agent/qwen2.5-coder-1.5b" -Recurse -Force
```

## 🔧 Configurar cuál modelo usa la app

El modelo se elige vía variable de entorno. El prompt se configura automáticamente:

```bash
# Usar DeepSeek (default)
$env:SHINTTOOLS_MODEL_FILE = "deepseek-coder-1.3b-instruct.Q4_K_M.gguf"

# Usar Qwen
$env:SHINTTOOLS_MODEL_FILE = "Qwen2.5-Coder-1.5B-Instruct-Q4_K_M.gguf"
$env:SHINTTOOLS_MODELS_DIR = "core/models/agent/qwen2.5-coder-1.5b"

# Ejecutar app
python -m uvicorn core.main:app --reload
```

## 📊 Prompts

Los prompts están en `core/modules/agent/model_config.py`:

- **DeepSeek**: Conversacional, más natural
- **Qwen**: Instructivo, más directo

El sistema detecta automáticamente cuál modelo está cargado y usa el prompt correcto.

## ✅ Siguiente paso

Una vez decidas cuál funciona mejor:

1. Actualiza `DEFAULT_MODEL_FILE` en `llm_backend.py` (si quieres cambiar el default)
2. Borra la carpeta del modelo que no uses
3. Commit con mensaje: `chore: switch to [DeepSeek|Qwen] LLM`
