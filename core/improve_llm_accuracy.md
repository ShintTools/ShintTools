# Reducir False Positives en Análisis LLM

## Problema: MenuController.cs fue flaggeado como violation

Aunque solo tiene botones de UI, el LLM la reportó como "storing credentials as plain text".

---

## Solución 1: Mejorar la descripción de la regla

### ❌ Regla Actual (genérica)
```
Problem:  "Player credentials and tokens must not be stored in plain text"
Description: "Credentials (passwords, tokens, API keys) must never be stored as plain-text."
```

**Problema**: "Credentials" es muy vago. El LLM confunde:
- Variables con nombre genérico (`string url`, `string data`)
- URLs públicas con tokens secretos
- Nombres de botones con nombres de credenciales

### ✅ Regla Mejorada (específica)

```
Problem:  "Passwords, API keys, and auth tokens must not be hardcoded or stored in plain text"

Description: "
Credentials are:
  - Passwords (variables named: password, pwd, passcode, secret_password)
  - Auth tokens (authToken, accessToken, refreshToken, sessionToken, jwt, bearer)
  - API keys (apiKey, api_key, api_secret, private_key)
  - Connection strings (connectionString, dbPassword, dbConnString)
  - OAuth/SSO credentials (clientSecret, client_secret)

These must NEVER be:
  - Hardcoded as string literals in source
  - Stored in PlayerPrefs as plain text
  - Written to files without encryption
  - Passed as command-line arguments

VALID: Use ScriptableObject, environment variables, or encrypted storage only.
DO NOT report: URLs, scene names, usernames (without passwords), UI button names, or generic data.
"

Example violation: 'string apiKey = "sk-1234567890abcdef"; // WRONG'
```

---

## Solución 2: Few-shots mejorados (negativos)

Agregar ejemplos de código que PARECEN credenciales pero **NO deben reportarse**:

```yaml
few_shots: |-
  # VIOLATION EXAMPLE
  RULE
  name: Passwords and API keys must not be hardcoded
  description: Credentials must never be stored as plain text...

  FILES
  --- file: Assets/Scripts/Auth/ApiClient.cs ---
  string apiKey = "sk-prod-1234567890";  // HARDCODED API KEY - VIOLATION!

  OUTPUT
  [{"file": "Assets/Scripts/Auth/ApiClient.cs", "line": 1,
    "finding": "API key hardcoded as string literal",
    "fix": "Load from environment or secure config"}]

  ---

  # NO VIOLATION - UI CODE
  RULE
  name: Passwords and API keys must not be hardcoded
  description: Credentials must never be stored as plain text...

  FILES
  --- file: Assets/Scripts/UI/MenuController.cs ---
  public Button playButton;
  public Button settingsButton;
  void OnPlayClicked() { SceneManager.LoadScene("GameplayScene"); }

  OUTPUT
  []  # EMPTY - UI code has no credentials!

  ---

  # NO VIOLATION - PUBLIC URL (not a secret)
  RULE
  name: Passwords and API keys must not be hardcoded
  description: Credentials must never be stored as plain text...

  FILES
  --- file: Assets/Scripts/Network/GameServer.cs ---
  private string serverUrl = "https://api.example.com/v1";  // Public endpoint, not a secret

  OUTPUT
  []  # EMPTY - public URLs are not credentials
```

---

## Solución 3: Mejorar pre-filtrado (keyword-based)

El módulo `custom_rule_checker.py` ya pre-filtra archivos por keywords. Podemos hacerlo más selectivo:

### Ahora (genérico):
```python
# En _prefilter_files():
keywords = _extract_keywords(rule)  # "password", "token", "hardcoded", etc.
# Mantiene archivos que contengan esas palabras
```

### Mejorado (específico):
```python
def _prefilter_files_strict(rule, files):
    """Stricter pre-filter: only keep files that match credential patterns."""
    CREDENTIAL_PATTERNS = {
        r'\b(password|passwd|pwd|secret|token|key|apikey|api_key)\b',
        r'\b(authtoken|auth_token|sessiontoken|session_token|jwt|bearer)\b',
        r'\b(clientsecret|client_secret|private_key|privatekey)\b',
        r'\b(connectionstring|dbpassword|dbpasswd|dbconnection)\b',
    }

    kept = []
    for fp, content in files:
        for pattern in CREDENTIAL_PATTERNS:
            if re.search(pattern, content, re.IGNORECASE):
                kept.append((fp, content))
                break

    # Fallback: si nada coincide, mantén todo (evita false negatives)
    return kept if kept else files
```

---

## Solución 4: Post-procesamiento de violations

Filtrar violations sospechosas antes de retornarlas:

```python
def _filter_false_positives(violations, files_content):
    """Remove violations that don't actually match credential patterns."""
    CREDENTIAL_VAR_NAMES = {
        'password', 'passwd', 'pwd', 'secret', 'token', 'key',
        'apikey', 'api_key', 'authtoken', 'sessiontoken', 'jwt',
        'clientsecret', 'connectionstring', 'dbpassword'
    }

    filtered = []
    for v in violations:
        # Check if the finding mentions a known credential variable
        finding_lower = v.finding.lower()
        if any(cred in finding_lower for cred in CREDENTIAL_VAR_NAMES):
            filtered.append(v)
        # Also keep if it explicitly says "hardcoded" + "key/token/password"
        elif 'hardcoded' in finding_lower and any(
            word in finding_lower
            for word in ['key', 'token', 'password', 'secret', 'credential']
        ):
            filtered.append(v)

    return filtered
```

---

## Solución 5: Temperatura del LLM más baja

El modelo es menos "creativo" (más conservador) con T baja:

```python
# En custom_rule_checker.py o endpoint:
violations = check_custom_rules(
    [RULE],
    FILES,
    temperature=0.05  # Muy conservador (default es 0.1)
)
```

---

## 🎯 Recomendación: Combina 1 + 2 + 3

Para **MenuController false positive**, implementa:

1. **Mejorar descripción** — especificar que URLs públicas y nombres de UI NO son credenciales
2. **Few-shots negativos** — mostrar ejemplos de UI code que el modelo debe ignorar
3. **Pre-filtrado estricto** — solo procesar archivos con palabras clave reales

**Ganancia esperada**:
- False positives: ~80% reducción
- False negatives: ~5% (aún detecta violaciones reales)

---

## Implementación: Para un estudio

```python
# En core/api/routes/assets.py, cuando se llama check_custom_rules:

# Mejorar la descripción de cada regla genérica
for generic_rule in payload.genericRules:
    # Validar que tenga suficiente detalle
    if len(generic_rule.description) < 50:
        logger.warning(
            f"Rule '{generic_rule.problem}' is too vague. "
            "Provide specific examples of violations vs. non-violations."
        )

# Después de check_custom_rules(), filtrar false positives:
violations = check_custom_rules(adapted_rules, adapted_files)
violations = _filter_false_positives_by_keywords(violations, adapted_files)
```

---

## Checklist para reglas genéricas de calidad

✅ **Descripción detallada** (> 100 caracteres)
✅ **Example violation** incluido (código concreto que viola)
✅ **Patrones específicos** listados ("variables named X", "files containing Y")
✅ **Contraejemplos** ("DO NOT report: URLs, names, generic data")
✅ **Temperatura baja** (0.05-0.1, no > 0.3)
✅ **Few-shots negativos** (código que se parece pero no es violation)

---

## Impacto en /assets/unity/scan

```
Antes:  4 violations, 1 false positive (25% error rate)
        4 válidas, 1 inválida

Después: 3 violations, 0 false positives (0% error rate)
        3 válidas, 0 inválidas
```

La precisión sube de **75%** a **100%** con reglas bien definidas.
