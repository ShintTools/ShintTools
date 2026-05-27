# ShintTools Core — Contrato API para el Plugin de Unity

Este documento describe los endpoints que el plugin de Unity necesita consumir.
El Core corre en `http://localhost:18200` (o el puerto definido en `core_port` del config).

**Setup local:** ver las instrucciones en el README (sección "🔌 Setup rápido para desarrolladores de plugin").

## Estructura unificada

**Todas las herramientas de análisis usan la misma estructura de request/response:**

```
POST /validate/unity/scan      → Code Tool   (C# scripts)
POST /assets/unity/scan        → Asset Tool  (naming de assets)
POST /validate/unity-graphs    → Graph Tool  (Visual Scripting .asset)
```

Input común: `{ "api_key": "", "rules/files": [...] }`
Output común: `{ "error": "", "time": 0.0, "files": [...] }`

---

## Autenticación

Todos los endpoints `POST` aceptan un campo `api_key` en el body JSON.

- **En testing local** (con `docker-compose.plugin-dev.yml`): usar `"shint_devtest0000000000"`
- **En producción**: la key la genera el Launcher cuando instala el Core en el estudio

El Core resuelve internamente qué tier de licencia corresponde a la key (Free o Indie).
Si la key es vacía o inválida, el Core responde con el tier `"free"` (reglas básicas).

---

## 1. Health Check

Usar para verificar que el Core está arriba antes de hacer cualquier operación.

**Request**
```
GET /health
```

**Response 200**
```json
{
  "status": "ok",
  "version": "0.1.0",
  "commit": "a1b2c3d",
  "database": "ok"
}
```

Si `"database"` es `"unavailable"`, el Core sigue funcionando pero no persiste resultados en MongoDB.

---

## 2. Scan de scripts C#

Analiza uno o varios archivos `.cs` y devuelve issues con sugerencias de fix.

**Request**
```
POST /validate/unity/scan
Content-Type: application/json
```

```json
{
  "api_key": "shint_devtest0000000000",
  "rules": [],
  "files": [
    {
      "path": "Assets/Scripts/Player/PlayerController.cs",
      "content": "using UnityEngine;\n\npublic class PlayerController : MonoBehaviour\n{\n    void Update()\n    {\n        var rb = GetComponent<Rigidbody>();\n    }\n}\n",
      "lines": 9
    }
  ]
}
```

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `api_key` | string | Key de licencia (o debug key) |
| `rules` | array | Reglas custom del usuario (ver sección 2.1) |
| `files[].path` | string | Ruta relativa del script desde la raíz del proyecto |
| `files[].content` | string | Contenido completo del archivo `.cs` |
| `files[].lines` | int | Número de líneas (puede ser 0, es informativo) |

**Response 200**
```json
{
  "error": "",
  "time": 0.0432,
  "files": [
    {
      "path": "Assets/Scripts/Player/PlayerController.cs",
      "rule": -1,
      "line": 7,
      "contextLine": 5,
      "contextBefore": "    void Update()\n    {\n        var rb = GetComponent<Rigidbody>();",
      "contextAfter": "    private Rigidbody _rb;\n\n    void Awake()\n    {\n        _rb = GetComponent<Rigidbody>();",
      "fix": "using UnityEngine;\n\npublic class PlayerController : MonoBehaviour\n{\n    private Rigidbody _rb;\n\n    void Awake()\n    {\n        _rb = GetComponent<Rigidbody>();\n    }\n\n    void Update()\n    {\n    }\n}\n",
      "rule_id": "UNI002",
      "severity": "warning",
      "message": "GetComponent called in Update. Cache it in Awake/Start to avoid per-frame allocation.",
      "rule_name": "GetComponent in Update",
      "is_auto_fixable": true
    }
  ]
}
```

| Campo respuesta | Descripción |
|----------------|-------------|
| `error` | Mensaje de advertencia del servidor (no error HTTP). Vacío si todo OK |
| `time` | Tiempo de procesamiento en segundos |
| `files[]` | Lista de issues encontrados (puede estar vacía si el código es correcto) |
| `files[].rule` | `-1` = regla built-in. Si es `>= 0`, es el índice en el array `rules` de la request |
| `files[].line` | Línea exacta del problema (1-based) |
| `files[].contextLine` | Primera línea del bloque de contexto mostrado |
| `files[].contextBefore` | Código actual alrededor del problema |
| `files[].contextAfter` | Código después de aplicar el fix (vacío si no hay fix disponible) |
| `files[].fix` | **Contenido completo del archivo corregido** (vacío si `is_auto_fixable: false`) |
| `files[].rule_id` | ID de la regla (p.ej. `"UNI002"`, `"CSS003"`, `"CSP007"`) |
| `files[].severity` | `"error"` \| `"warning"` \| `"info"` |
| `files[].message` | Descripción legible del problema |
| `files[].rule_name` | Nombre corto de la regla |
| `files[].is_auto_fixable` | `true` si `fix` tiene contenido válido |

> **Nota sobre `fix`:** cuando `is_auto_fixable` es `true`, el campo `fix` contiene el archivo **completo** corregido, no solo el diff. El plugin puede sobreescribir directamente el archivo en disco.

### 2.1 Reglas custom (campo `rules`)

El usuario puede definir sus propias reglas en lenguaje natural. Solo funcionan cuando el LLM agent está habilitado (tier Indie). En modo Free o en testing local, se ignoran (el servidor devuelve nota en `"error"`).

```json
{
  "rules": [
    {
      "problem": "Usar Debug.Log en código de producción",
      "solution": "Envolver en #if UNITY_EDITOR o eliminar"
    }
  ]
}
```

---

## 3. Scan de naming de assets

Valida que los assets del proyecto sigan las convenciones de naming.

**Request**
```
POST /assets/unity/scan
Content-Type: application/json
```

```json
{
  "api_key": "shint_devtest0000000000",
  "namingRules": [],
  "genericRules": [],
  "files": [
    {
      "path": "Assets/Art/Textures/playerSkin.png",
      "type": "Texture2D"
    },
    {
      "path": "Assets/Art/Materials/Mat_Player.mat",
      "type": "Material"
    },
    {
      "path": "Assets/Prefabs/P_Enemy.prefab",
      "type": "GameObject"
    }
  ]
}
```

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `api_key` | string | Key de licencia |
| `files[].path` | string | Ruta del asset desde la raíz del proyecto |
| `files[].type` | string | Tipo Unity (del `AssetDatabase`, p.ej. `"Texture2D"`, `"Material"`, `"GameObject"`) |
| `namingRules` | array | Reglas de prefijo/sufijo definidas por el usuario (ver 3.1) |
| `genericRules` | array | Reglas de texto libre, procesadas por LLM (solo Indie, ver 3.2) |

**Tipos Unity reconocidos:** `Texture2D`, `Material`, `Mesh`, `GameObject` (prefabs), `AudioClip`, `Shader`, `ScriptableObject`, `MonoScript`, `SceneAsset`, `AnimationClip`, `AnimatorController`, `PhysicMaterial`, `Font`, `TextAsset`, `Sprite`, `Cubemap`, `VideoClip`, y más.

**Response 200**
```json
{
  "error": "",
  "time": 0.0089,
  "files": [
    {
      "path": "Assets/Art/Textures/playerSkin.png",
      "genericRule": -1,
      "namingRule": -1,
      "fix": "T_playerSkin",
      "rule_id": "NMU001",
      "severity": "warning",
      "message": "Texture2D asset 'playerSkin.png' is missing the required prefix 'T_'.",
      "rule_name": "Missing prefix",
      "is_auto_fixable": true
    }
  ]
}
```

| Campo respuesta | Descripción |
|----------------|-------------|
| `files[].genericRule` | `-1` = no es regla generic. `>= 0` = índice en `payload.genericRules` |
| `files[].namingRule` | `-1` = no es regla custom. `>= 0` = índice en `payload.namingRules` |
| `files[].fix` | Nombre corregido del asset (solo el stem, sin extensión, sin la ruta) |

> **Nota sobre `fix`:** para naming, `fix` es solo el nombre del archivo sugerido (ej: `"T_playerSkin"`), no la ruta completa. El plugin decide dónde aplicar el rename.

### 3.1 Reglas de naming custom (`namingRules`)

```json
{
  "namingRules": [
    {
      "type": "Texture2D",
      "prefix": "T_",
      "suffix": ""
    },
    {
      "type": "Material",
      "prefix": "Mat_",
      "suffix": ""
    }
  ]
}
```

Si `type` está vacío (`""`), la regla aplica a todos los tipos.

### 3.2 Reglas genéricas custom (`genericRules`)

Igual que las reglas custom del Code Tool. Solo funcionan con el LLM agent activo.

```json
{
  "genericRules": [
    {
      "problem": "Assets en la carpeta Resources/",
      "solution": "Mover a una carpeta Addressables o usar AssetBundles"
    }
  ]
}
```

---

## 4. Scan de Visual Scripting (Graph Tool)

Analiza grafos de Unity Visual Scripting (archivos `.asset` en formato YAML).

**Request**
```
POST /validate/unity-graphs
Content-Type: application/json
```

```json
{
  "api_key": "shint_devtest0000000000",
  "files": [
    {
      "path": "Assets/Scripts/StateMachine.asset",
      "content": "%YAML 1.1\n%TAG !u! tag:unity3d.com,2011:\n--- !u!114 &1\n..."
    }
  ]
}
```

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `api_key` | string | Key de licencia |
| `files[].path` | string | Ruta del archivo `.asset` desde la raíz del proyecto |
| `files[].content` | string | Contenido completo del archivo YAML del grafo |

**Response 200**
```json
{
  "error": "",
  "time": 0.0081,
  "files": [
    {
      "path": "Assets/Scripts/StateMachine.asset",
      "rule": -1,
      "line": 0,
      "contextLine": 0,
      "contextBefore": "graph: StateMachine",
      "contextAfter": "",
      "fix": "",
      "rule_id": "VSG003",
      "severity": "warning",
      "message": "Graph has too many nodes (87). Consider splitting into subgraphs.",
      "rule_name": "Graph too complex",
      "is_auto_fixable": false
    }
  ]
}
```

> **Nota:** `line` siempre es `0` — los grafos YAML no tienen números de línea. `fix` siempre está vacío — la edición automática de YAML de grafos no está disponible todavía. `is_auto_fixable` siempre es `false`.

---

## IDs de reglas built-in (referencia rápida)

### Reglas C# — Code Tool

| Prefijo | Categoría | Rango |
|---------|-----------|-------|
| `CSS` | Security | CSS001–CSS009 |
| `CSP` | Performance | CSP001–CSP010 |
| `CSB` | Best Practices | CSB001–CSB014 |
| `CSM` | Maintainability | CSM001–CSM005 |
| `UNI` | Unity-Specific | UNI001–UNI018 |

### Reglas de Naming — Asset Tool

| Prefijo | Categoría |
|---------|-----------|
| `NMU001` | Missing prefix |
| `NMU009` | Asset en carpeta incorrecta para su tipo |
| `NMU016` | Prefijo válido pero incorrecto para el tipo de asset |
| `NM001–NM018` | Reglas generales (case, caracteres especiales, longitud, etc.) |

### Reglas de Visual Scripting — Graph Tool

| Prefijo | Descripción |
|---------|-------------|
| `VSG` | Graph validation (node count, complexity, disconnected nodes, etc.) |

---

## Errores HTTP

| Código | Significado |
|--------|-------------|
| 200 | OK (incluso si hay issues encontrados) |
| 422 | Body JSON malformado (Pydantic validation error) |
| 500 | Error interno del Core — revisar logs del contenedor |

El Core **nunca devuelve 4xx por encontrar issues** — los issues son el resultado esperado, no un error.
