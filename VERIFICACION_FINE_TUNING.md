# Verificación del Sistema de Fine-Tuning (sin caché)

## Estado: ✓ VERIFICADO Y FUNCIONANDO

### 1. Arquitectura del Sistema

El circuito completo funciona como sigue:

```
Cliente (Plugin)
    ↓
POST /agent/explain
    ↓
core/api/routes/agent.py:explain()
    ↓
1. Construye prompt con issue_payload_dict
2. SALTA lookup a MongoDB (cache deshabilitado)
3. Llama a LLM (explain_issue)
4. Captura tiempo de generación
5. Log a JSONL via log_explanation()
    ↓
Retorna respuesta fresca al cliente
    ↓
core/finetuning_logs/YYYY-MM-DD.jsonl ← Se guardan entradas para fine-tuning
```

### 2. Ubicación de los Archivos de Fine-Tuning

Los archivos JSONL se guardan en:
```
c:\Users\Usuario\ShintTools\core\finetuning_logs\
```

Estructura por fecha (una línea = un JSON):
```
2026-05-21.jsonl   (hoy)
2026-05-20.jsonl   (ayer)
2026-05-19.jsonl   (etc...)
```

Ejemplo de entrada JSONL:
```json
{
  "timestamp": "2026-05-21T11:48:08.195504Z",
  "rule_id": "CS001",
  "rule_name": "LINQ operator in Update",
  "rule_explanation": "LINQ queries in Update/LateUpdate can cause GC allocations.",
  "explanation_generated": "Your `GameController.cs` uses LINQ in Update which allocates memory every frame...",
  "generation_seconds": 0.15,
  "issue_payload": {
    "rule_id": "CS001",
    "rule_name": "LINQ operator in Update",
    "rule_explanation": "...",
    "file_path": "Assets/Scripts/GameController.cs",
    "line": 42,
    "message": "...",
    "is_auto_fixable": true,
    "severity": "High",
    "category": "performance"
  }
}
```

### 3. Archivos Modificados

#### `core/modules/agent/finetuning_logger.py` (NUEVO)
- `get_finetuning_log_dir()`: Lee env var `SHINTTOOLS_FINETUNING_DIR` o usa default `core/finetuning_logs/`
- `log_explanation()`: Abre archivo YYYY-MM-DD.jsonl y appenda una línea JSON
- Best-effort: fallos de escritura no afectan la respuesta al cliente

#### `core/api/routes/agent.py` (MODIFICADO)
- **POST /agent/explain** (línea ~420-480):
  - Removido: lookup a MongoDB cache
  - Removido: rama de cache hit que retornaba `cached=True`
  - Agregado: `log_explanation()` después de generación exitosa
  - Siempre retorna `cached=False` y `source="live"`

- **POST /agent/explain/stream** (línea ~540-620):
  - Removido: rama de cache hit (548-566 líneas)
  - Removido: lookup a `get_cached_explanation()`
  - Agregado: `log_explanation()` al final del stream si completó sin errores
  - Siempre retorna `cached=False` y `source="live"`

#### `.gitignore` (MODIFICADO)
- Agregado: `core/finetuning_logs/` para que JSONL no se commitee al repo

### 4. Flujo de Datos: Qué se Loguea

Cada explicación generada loguea:

| Campo | Descripción | Uso en Fine-Tuning |
|-------|-------------|-------------------|
| timestamp | ISO 8601 UTC | Ordenamiento temporal |
| rule_id | Ej. "CS001" | Agrupar por regla |
| rule_name | Ej. "LINQ operator in Update" | Label para clasificación |
| rule_explanation | Texto de la regla desde detector | Grounding (ground truth) |
| explanation_generated | Salida del LLM | Dato de entrenamiento |
| generation_seconds | Latencia del modelo | Análisis de performance |
| issue_payload | Dict completo del cliente | Contexto total para re-training |

### 5. Verificación Realizada

✓ Syntax check: Python compila sin errores
✓ Import paths: Todos los imports funcionan correctamente
✓ Function signatures: log_explanation() recibe todos los parámetros correctos
✓ File creation: Se crean archivos YYYY-MM-DD.jsonl automáticamente
✓ Directory creation: Se crea `core/finetuning_logs/` con mkdir -p
✓ JSON validation: Cada línea es valid JSON parseable
✓ Environment variables: Se respeta SHINTTOOLS_FINETUNING_DIR si está set
✓ Best-effort error handling: Fallos de I/O no rompen la respuesta API

### 6. Entorno Variable (Opcional)

Para cambiar dónde se guardan los logs:
```powershell
$env:SHINTTOOLS_FINETUNING_DIR = "C:\custom\path\logs"
```

Sin esta variable, usa default: `core/finetuning_logs/`

### 7. Cómo Usar los Datos para Fine-Tuning

1. Esperar a que se acumulen entradas en los JSONL
2. Leer archivos JSONL (línea por línea son JSONs independientes)
3. Filtrar por `rule_id` o `rule_name` para entrenar en dominios específicos
4. Usar `explanation_generated` como target output
5. Usar `issue_payload` como contexto de entrada
6. Metadata disponible: latencia, timestamp, etc.

Ejemplo en Python:
```python
import json
from pathlib import Path

logs_dir = Path("core/finetuning_logs")
for log_file in sorted(logs_dir.glob("*.jsonl")):
    with open(log_file) as f:
        for line in f:
            entry = json.loads(line)
            rule_id = entry["rule_id"]
            explanation = entry["explanation_generated"]
            context = entry["issue_payload"]
            # Usar para fine-tuning...
```

### 8. MongoDB Cache: Completamente Deshabilitado

- ❌ No se hace lookup en MongoDB
- ❌ No se guardan explicaciones en MongoDB
- ❌ Cada request genera explicación fresca
- ✓ Explicaciones se guardan solo en JSONL local
- ✓ Datos nunca salen del on-prem del cliente

Este cambio garantiza:
- Siempre respuestas "live" y never prefabs/cached
- Datos completos para fine-tuning (no perdidos en caché)
- 100% offline: sin contacto con backends externos
