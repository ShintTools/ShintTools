# ShintTools API Reference

## Resumen Técnico

### Asset Tool (Validación de Nomenclatura)

El **Asset Tool** detecta problemas de naming en assets de Unity y UE5. Funciona con tres capas complementarias:

1. **Capa 1 — Reglas integradas** (todos los tiers)
   - Detecta prefijos incorrectos (`T_` para texturas, `M_` para materiales)
   - Espacios, mayúsculas en extensiones, assets en carpetas inválidas
   - Automático, sin configuración

2. **Capa 2 — Reglas de naming personalizadas** (Indie+)
   - El estudio define prefijo/sufijo por tipo de asset
   - Determinístico: no usa LLM, puramente pattern-matching
   - Respuesta instantánea

3. **Capa 3 — Reglas genéricas con LLM** (Indie+)
   - El estudio escribe reglas en lenguaje natural
   - El LLM analiza el código/contenido del asset
   - Requiere `SHINTTOOLS_AGENT_ENABLED=1` en el servidor

**Tier gating:**
- **Free**: Capa 1 únicamente
- **Indie**: Capas 1, 2, 3
- **Studio**: Capas 1, 2, 3 + LOD Auditor

---

### LOD Auditor (Análisis de Rendimiento)

Detecta configuraciones que desperdician VRAM o GPU en assets de textura, material y mesh.

**Capa 1 — Básica** (todos los tiers)
- LT001: Compresión no óptima para uso (BC7 vs BC4, etc.)
- LT003: Resolución excede presupuesto del LOD group

**Capas 2-3 — Completas** (Studio únicamente)
- Textures: LT001, LT002, LT003, LT004, LT005
- Materials: LM001, LM002, LM003
- Meshes: LD001, LD002, LD003

Cada finding incluye:
- **VRAM saved**: Cuántos MB se ahorran si se aplica el fix
- **Auto-fixable**: Boolean si el servidor puede corregirlo automáticamente
- **Guidance**: Explicación del problema y cómo arreglarlo (con LLM en Studio)

---

## Endpoints

### 1. Asset Tool: POST `/assets/unity/scan`

**Contrato**: Escanea assets de Unity con 3 capas de validación.

#### Request

```json
{
  "api_key": "sk_...",
  "files": [
    {
      "path": "Assets/Materials/Wood.mat",
      "type": "Material"
    },
    {
      "path": "Assets/Textures/Hero_Diffuse.png",
      "type": "Texture2D"
    }
  ],
  "namingRules": [
    {
      "type": "Texture2D",
      "prefix": "T_",
      "suffix": ""
    },
    {
      "type": "Material",
      "prefix": "M_",
      "suffix": ""
    }
  ],
  "genericRules": [
    {
      "problem": "Textura sin mipmap",
      "solution": "El asset debe tener mipmap habilitado si está en Shader"
    }
  ]
}
```

#### Response

```json
{
  "error": "",
  "time": 0.345,
  "files": [
    {
      "path": "Assets/Materials/Wood.mat",
      "genericRule": -1,
      "namingRule": 1,
      "fix": "M_Wood",
      "rule_id": "NM001",
      "severity": "warning",
      "message": "Material debe usar prefijo M_",
      "rule_name": "Built-in Material Naming",
      "is_auto_fixable": true
    },
    {
      "path": "Assets/Textures/Hero_Diffuse.png",
      "genericRule": 0,
      "namingRule": -1,
      "fix": "",
      "rule_id": "GR001",
      "severity": "warning",
      "message": "Texture sampled in Shader but mipmap disabled",
      "rule_name": "Custom: Textura sin mipmap",
      "is_auto_fixable": false
    }
  ]
}
```

**Campo explicaciones:**
- `genericRule`: Índice en `genericRules` del request (-1 si no aplica)
- `namingRule`: Índice en `namingRules` del request (-1 si no aplica)
- `fix`: Nombre corregido (stem only, sin extensión)
- `rule_id`: Identificador único de la regla (ej: NM001 built-in, GR001 genérica)

---

### 2. Asset Tool: POST `/agent/explain`

**Contrato**: Explicación sincrónica de un issue específico (espera hasta 40s en CPU).

#### Request

```json
{
  "api_key": "sk_...",
  "issue": {
    "rule_id": "NM001",
    "rule_name": "Material Naming Convention",
    "rule_explanation": "Materials in UE5 must start with M_ prefix",
    "file_path": "Assets/Materials/Wood.mat",
    "asset_path": "Assets/Materials/Wood.mat",
    "message": "Material should use M_ prefix",
    "is_auto_fixable": true,
    "severity": "warning"
  }
}
```

#### Response

```json
{
  "explanation": "Materials in Unreal Engine follow a strict naming convention using M_ prefix to ensure consistency in asset organization. The Material Instance requires this naming pattern for automatic sorting in the Content Browser. Fix: rename to M_Wood."
}
```

---

### 3. Asset Tool: POST `/agent/explain/stream`

**Contrato**: Explicación vía SSE (Server-Sent Events). El cliente recibe tokens mientras se generan.

#### Request

Mismo schema que `/agent/explain`.

#### Response (Server-Sent Events)

```
data: {"chunk":"Materials"}

data: {"chunk":" in Unreal"}

data: {"chunk":" Engine follow"}

...

data: {"done":true,"full_text":"Materials in Unreal Engine follow...","cached":false,"source":"live","generation_seconds":23.45}

```

**Eventos SSE:**
- `{"chunk": "..."}` — Fragmento de texto generado por el LLM (múltiples)
- `{"error": "..."}` — Error fatal (LLM no cargado, etc.)
- `{"done": true, "full_text": "...", "cached": false, "generation_seconds": 23.45}` — Fin del stream

---

### 4. LOD Auditor: POST `/assets/lod/audit`

**Contrato**: Audita assets para detectar desperdicios de VRAM y GPU.

**Tier gating:**
- Free: 403 (LOD Auditor requires Studio)
- Indie: 403 (LOD Auditor requires Studio)
- Studio: 200 (todas las reglas ejecutadas)

#### Request

```json
{
  "api_key": "sk_...",
  "assets": [
    {
      "asset_path": "Assets/Textures/Hero_Diffuse.png",
      "asset_type": "Texture2D",
      "usage": "BaseColor",
      "compression": "RGBA8",
      "resolution_x": 4096,
      "resolution_y": 4096,
      "streaming_enabled": false,
      "vert_count": 0,
      "lod_count": 0
    },
    {
      "asset_path": "Assets/Materials/Wood.mat",
      "asset_type": "Material",
      "usage": "",
      "compression": "",
      "resolution_x": 0,
      "resolution_y": 0,
      "streaming_enabled": false,
      "vert_count": 0,
      "lod_count": 0
    }
  ]
}
```

#### Response

```json
{
  "error": "",
  "time": 0.234,
  "summary": {
    "assets_audited": 2,
    "issues_found": 2,
    "auto_fixable": 2,
    "estimated_vram_saved_mb": 42.56,
    "estimated_shader_instructions_saved": 0
  },
  "results": [
    {
      "asset_path": "Assets/Textures/Hero_Diffuse.png",
      "rule_id": "LT001",
      "category": "Texture",
      "severity": "warning",
      "message": "Usage 'BaseColor' expects BC7 compression, but 'RGBA8' was found. Wrong format degrades quality or wastes VRAM.",
      "auto_fixable": true,
      "current": {
        "compression": "RGBA8"
      },
      "recommended": {
        "compression": "BC7"
      },
      "guidance": null,
      "estimated_saving": {
        "vram_mb": 32.0,
        "shader_instructions": 0
      },
      "detailed_guidance": "BC7 is the optimal codec for BaseColor textures, providing better quality than RGBA8 while saving VRAM through compression. Switch in the Texture Asset settings."
    },
    {
      "asset_path": "Assets/Textures/Hero_Diffuse.png",
      "rule_id": "LT005",
      "category": "Texture",
      "severity": "info",
      "message": "4096×4096 texture has streaming disabled — it occupies 68.27 MB of VRAM permanently. Enable streaming so the engine unloads it when not visible.",
      "auto_fixable": true,
      "current": {
        "streaming": false,
        "resident_vram_mb": 68.27
      },
      "recommended": {
        "streaming": true
      },
      "guidance": "Streaming allows UE5 to page textures in/out of VRAM based on visibility, reducing peak memory usage.",
      "estimated_saving": {
        "vram_mb": 10.56,
        "shader_instructions": 0
      }
    }
  ]
}
```

---

## Códigos de Error

### HTTP Status

| Código | Significado | Ejemplo |
|--------|------------|---------|
| 200 | OK — Auditoría completada (con/sin issues) | `{...}` |
| 403 | Tier no autorizado | `{"detail": "LOD Auditor requires Studio"}` |
| 422 | Request inválido (schema) | `{"detail": "validation error..."}` |
| 500 | Error del servidor | `{"error": "unexpected server error"}` |

### Response `error` field

Si el servidor completa pero encuentra un problema interno:

```json
{
  "error": "LLM model not loaded",
  "time": 0.001,
  "summary": {...},
  "results": []
}
```

---

## Tier Gating Resumen

| Feature | Free | Indie | Studio |
|---------|------|-------|--------|
| Asset Naming — Layer 1 (built-in) | ✓ | ✓ | ✓ |
| Asset Naming — Layer 2 (custom prefix/suffix) | ✗ | ✓ | ✓ |
| Asset Naming — Layer 3 (generic LLM rules) | ✗ | ✓ | ✓ |
| LOD Auditor | ✗ | ✗ | ✓ |
| Streaming explanations (`/agent/explain/stream`) | ✗ | ✓ | ✓ |

---

## Cómo integrar en el Plugin (Unity)

### 1. Enviar assets para validar naming

```csharp
var request = new AssetScanRequest
{
    api_key = EditorPrefs.GetString("ShintTools_ApiKey"),
    files = GetSelectedAssets().Select(a => new UnityAssetFile {
        path = AssetDatabase.GetAssetPath(a),
        type = a.GetType().Name
    }).ToList(),
    namingRules = LoadNamingRules(), // Rules del studio
    genericRules = LoadGenericRules()  // Rules genéricas
};

var response = await client.PostAsync("/assets/unity/scan", request);
```

### 2. Solicitar explicación de un issue

```csharp
var request = new AgentExplainRequest
{
    api_key = EditorPrefs.GetString("ShintTools_ApiKey"),
    issue = new Issue {
        rule_id = finding.rule_id,
        rule_name = finding.rule_name,
        rule_explanation = finding.rule_explanation,
        asset_path = finding.asset_path,
        is_auto_fixable = finding.is_auto_fixable
    }
};

// Sincrónico: espera hasta 40s
var response = await client.PostAsync("/agent/explain", request);
EditorUtility.DisplayDialog("Explanation", response.explanation);

// O streaming: recibe tokens mientras se generan
await client.StreamAsync("/agent/explain/stream", request, chunk => {
    explanationText += chunk;
    EditorUtility.ClearProgressBar();
});
```

### 3. Auditar assets para LOD

```csharp
var request = new LodAuditRequest
{
    api_key = EditorPrefs.GetString("ShintTools_ApiKey"),
    assets = GetProjectAssets().Select(a => new LodAssetFile {
        asset_path = AssetDatabase.GetAssetPath(a),
        asset_type = a.GetType().Name,
        usage = GetTextureUsage(a),
        compression = GetTextureCompression(a),
        resolution_x = GetWidth(a),
        resolution_y = GetHeight(a),
        streaming_enabled = GetStreamingFlag(a)
    }).ToList()
};

var response = await client.PostAsync("/assets/lod/audit", request);
foreach (var finding in response.results) {
    EditorGUILayout.LabelField($"{finding.rule_id}: {finding.message}");
    EditorGUILayout.LabelField($"  Save {finding.estimated_saving.vram_mb} MB VRAM");
}
```

---

## Performance

| Operación | Tiempo (CPU) | Notas |
|-----------|--------------|-------|
| Asset naming (Layer 1-2) | <100ms | Determinístico, local |
| Asset naming (Layer 3 + LLM) | 20-40s | Depende de cantidad de assets |
| LOD audit | <500ms | Determinístico |
| `/agent/explain` (sync) | 20-40s | Primera llamada: cold cache; siguientes: ~5s |
| `/agent/explain/stream` | 20-40s | Tokens cada ~100ms |

---

## Logging (servidor)

Todos los endpoints loguean a:
- `shinttools.assets` (naming rules)
- `shinttools.lod_audit` (LOD Auditor)
- `shinttools.agent` (explanations)

Ej:
```
INFO:shinttools.assets:/assets/unity/scan: tier=indie files=42 namingRules=3 genericRules=1
DEBUG:shinttools.assets:/assets/unity/scan: layer1=3 findings
DEBUG:shinttools.assets:/assets/unity/scan: layer2=1 findings
DEBUG:shinttools.assets:/assets/unity/scan: layer3 calling LLM with 1 rules, 42 files
INFO:shinttools.assets:/assets/unity/scan: layer3=2 findings
```

---

## Variables de Entorno (servidor)

- `SHINTTOOLS_AGENT_ENABLED=1` — Habilita Layer 3 (LLM) en Asset Tool y explanations en LOD Auditor
- `SHINTTOOLS_MODEL_FILE=path/to/model.gguf` — Ruta custom del modelo LLM
- Base de datos: `MONGODB_URI` para caching (si se implementa en futuro)
