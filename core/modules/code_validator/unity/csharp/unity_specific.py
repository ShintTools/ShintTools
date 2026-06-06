# core/modules/code_validator/rules/csharp/unity_specific.py
#
# Unity-specific rule detectors - UN001-UN025 (16 implemented).
#
# UN001  FindObject in Update
# UN002  GetComponent in Update
# UN003  FindObjectOfType in Update
# UN004  Debug.Log in Update
# UN005  SendMessage use
# UN006  Public field on MonoBehaviour
# UN007  Empty Update
# UN008  Camera.main in Update
# UN009  Coroutine leak (no StopAllCoroutines in OnDestroy)
# UN010  Rigidbody physics in Update
# UN011  transform written inside a loop
# UN012  .tag string compare
# UN013  GetComponent in Awake without [RequireComponent]
# UN014  DontDestroyOnLoad without singleton guard
# UN015  Resources.Load usage
# UN016  ScriptableObject without [CreateAssetMenu]
# Total: 16 rules

from __future__ import annotations

import re
from typing import List

from code_validator.unity.csharp._csharp_helpers import (
    Issue,
    _emit,
    _find_method_body,
    _line_number,
    _update_body,
)


def detect_findobject_in_update(content: str, file_path: str) -> List[Issue]:
    """UN001: GameObject.Find inside Update - O(scene) every frame."""
    body = _update_body(content)
    if not body:
        return []
    region = content[body[0] : body[1]]
    m = re.search(r"\bGameObject\.Find\s*\(", region)
    if not m:
        return []
    line = _line_number(content, body[0] + m.start())
    return [
        _emit(
            file_path,
            line,
            content,
            rule_id="UN001",
            category="Performance",
            severity="error",
            message="GameObject.Find called inside Update - scans the entire scene every frame.",  # noqa: E501
            fix_suggestion="Cache the reference in Awake/Start; expose it as [SerializeField] when possible.",  # noqa: E501
        )
    ]


def detect_getcomponent_in_update(content: str, file_path: str) -> List[Issue]:
    """UN002: GetComponent inside Update - reflection per frame."""
    body = _update_body(content)
    if not body:
        return []
    region = content[body[0] : body[1]]
    m = re.search(r"\bGetComponent\s*<", region)
    if not m:
        return []
    line = _line_number(content, body[0] + m.start())
    return [
        _emit(
            file_path,
            line,
            content,
            rule_id="UN002",
            category="Performance",
            severity="error",
            message="GetComponent called inside Update - cache the result in Awake/Start.",  # noqa: E501
            fix_suggestion="Move GetComponent<T>() to Awake() and store in a private field.",  # noqa: E501
        )
    ]


def detect_findobjectoftype_in_update(content: str, file_path: str) -> List[Issue]:
    """UN003: FindObjectOfType / FindAnyObjectByType inside Update."""
    body = _update_body(content)
    if not body:
        return []
    region = content[body[0] : body[1]]
    m = re.search(
        r"\b(?:FindObjectOfType|FindAnyObjectByType|FindObjectsOfType|FindObjectsByType)\s*<",  # noqa: E501
        region,
    )
    if not m:
        return []
    line = _line_number(content, body[0] + m.start())
    return [
        _emit(
            file_path,
            line,
            content,
            rule_id="UN003",
            category="Performance",
            severity="error",
            message="FindObjectOfType called inside Update - scans every loaded object every frame.",  # noqa: E501
            fix_suggestion="Cache the reference in Awake/Start.",
        )
    ]


def detect_log_in_update(content: str, file_path: str) -> List[Issue]:
    """UN004: Debug.Log inside Update - IO + string format every frame."""
    body = _update_body(content)
    if not body:
        return []
    region = content[body[0] : body[1]]
    m = re.search(r"\bDebug\.(?:Log|LogWarning|LogError|LogFormat)\s*\(", region)
    if not m:
        return []
    line = _line_number(content, body[0] + m.start())
    return [
        _emit(
            file_path,
            line,
            content,
            rule_id="UN004",
            category="Performance",
            severity="warning",
            message="Debug.Log inside Update floods the console and serialises strings every frame.",  # noqa: E501
            fix_suggestion="Gate behind a #if UNITY_EDITOR / Conditional flag, or remove.",  # noqa: E501
        )
    ]


def detect_sendmessage_use(content: str, file_path: str) -> List[Issue]:
    """UN005: SendMessage / BroadcastMessage - reflection-based and slow."""
    out: List[Issue] = []
    for m in re.finditer(
        r"\b(?:SendMessage|SendMessageUpwards|BroadcastMessage)\s*\(", content
    ):
        line = _line_number(content, m.start())
        out.append(
            _emit(
                file_path,
                line,
                content,
                rule_id="UN005",
                category="Performance",
                severity="warning",
                message="SendMessage uses reflection at runtime - prefer typed events / interfaces.",  # noqa: E501
                fix_suggestion="Replace with a direct method call, UnityEvent, or C# event/delegate.",  # noqa: E501
            )
        )
    return out


def detect_public_field_monobehaviour(content: str, file_path: str) -> List[Issue]:
    """UN006: public field on a MonoBehaviour - prefer [SerializeField] private.

    Triggers when a class extends MonoBehaviour and exposes a non-static,
    non-property public field. Public fields are mutable from any caller
    and break encapsulation; SerializeField gives the same Inspector
    visibility while keeping the field internal.
    """
    cls_match = re.search(r"class\s+(\w+)\s*:[^{]*\bMonoBehaviour\b[^{]*\{", content)
    if not cls_match:
        return []
    # Restrict the scan to the class body
    body_start = cls_match.end()
    depth = 1
    end = body_start
    for i in range(body_start, len(content)):
        if content[i] == "{":
            depth += 1
        elif content[i] == "}":
            depth -= 1
            if depth == 0:
                end = i
                break
    region = content[body_start:end]
    out: List[Issue] = []
    field_re = re.compile(
        r"^[ \t]*public\s+(?!class\b|struct\b|enum\b|interface\b|static\b|const\b|override\b|virtual\b|abstract\b|event\b)"  # noqa: E501
        r"([\w<>,\s\[\]?]+?)\s+(\w+)\s*(?:=\s*[^;{]+)?;",
        re.MULTILINE,
    )
    for m in field_re.finditer(region):
        # Skip properties (have braces) and method declarations
        # (already excluded by the `;` anchor at end of regex).
        decl = m.group(0)
        if "{" in decl or "(" in decl:
            continue
        line = _line_number(content, body_start + m.start())
        out.append(
            _emit(
                file_path,
                line,
                content,
                rule_id="UN006",
                category="BestPractices",
                severity="warning",
                message=f"Public field '{m.group(2)}' on MonoBehaviour - prefer [SerializeField] private for Inspector exposure without breaking encapsulation.",  # noqa: E501
                fix_suggestion=f"[SerializeField] private {m.group(1).strip()} {m.group(2)};",  # noqa: E501
            )
        )
    return out


def detect_empty_update(content: str, file_path: str) -> List[Issue]:
    """UN007: empty Update method - Unity still invokes it every frame."""
    sig_re = r"\b(?:private|public|protected|internal)?\s*void\s+(?:Update|LateUpdate|FixedUpdate)\s*\(\s*\)"  # noqa: E501
    span = _find_method_body(content, sig_re)
    if not span:
        return []
    body = content[span[0] : span[1]].strip()
    # Strip comments
    body_no_comments = re.sub(r"//[^\n]*", "", body)
    body_no_comments = re.sub(
        r"/\*.*?\*/", "", body_no_comments, flags=re.DOTALL
    ).strip()
    if body_no_comments:
        return []
    line = span[2]
    return [
        _emit(
            file_path,
            line,
            content,
            rule_id="UN007",
            category="Performance",
            severity="warning",
            message="Empty Update/LateUpdate/FixedUpdate - Unity still pays the native->managed call overhead each frame.",  # noqa: E501
            fix_suggestion="Delete the method; Unity skips the per-frame call entirely.",  # noqa: E501
        )
    ]


def detect_camera_main_in_update(content: str, file_path: str) -> List[Issue]:
    """UN008: Camera.main inside Update.

    Camera.main is `GameObject.FindGameObjectWithTag("MainCamera")` under
    the hood - full scene tag scan every frame.
    """
    body = _update_body(content)
    if not body:
        return []
    region = content[body[0] : body[1]]
    m = re.search(r"\bCamera\.main\b", region)
    if not m:
        return []
    line = _line_number(content, body[0] + m.start())
    return [
        _emit(
            file_path,
            line,
            content,
            rule_id="UN008",
            category="Performance",
            severity="error",
            message="Camera.main inside Update - does a full FindGameObjectWithTag scan every frame.",  # noqa: E501
            fix_suggestion="Cache the camera reference in Awake/Start (private Camera _mainCam = Camera.main).",  # noqa: E501
        )
    ]


def detect_coroutine_leak(content: str, file_path: str) -> List[Issue]:
    """UN009: StartCoroutine without StopCoroutine/StopAllCoroutines in OnDestroy - coroutine fires on destroyed object."""  # noqa: E501
    if not re.search(r"\bStartCoroutine\s*\(", content):
        return []
    ondestroy_span = _find_method_body(
        content, r"\b(?:override\s+)?void\s+OnDestroy\s*\(\s*\)"
    )
    ondestroy_body = (
        content[ondestroy_span[0] : ondestroy_span[1]] if ondestroy_span else ""
    )
    if re.search(r"\bStop(?:All)?Coroutines?\s*\(", ondestroy_body):
        return []
    m = re.search(r"\bStartCoroutine\s*\(", content)
    if not m:
        return []
    line = _line_number(content, m.start())
    return [
        _emit(
            file_path,
            line,
            content,
            rule_id="UN009",
            category="Performance",
            severity="warning",
            message="StartCoroutine with no StopAllCoroutines in OnDestroy - Coroutine may fire callbacks on a destroyed MonoBehaviour.",  # noqa: E501
            fix_suggestion="Add `StopAllCoroutines();` at the start of OnDestroy.",
        )
    ]


def detect_physics_in_update(content: str, file_path: str) -> List[Issue]:
    """UN010: Rigidbody physics applied in Update - causes frame-rate-dependent jitter."""  # noqa: E501
    sig_re = r"\b(?:private|public|protected|internal)?\s*void\s+(?:Update|LateUpdate)\s*\(\s*\)"  # noqa: E501
    span = _find_method_body(content, sig_re)
    if not span:
        return []
    body = content[span[0] : span[1]]
    m = re.search(
        r"\b(?:\w+)\s*\.\s*(?:AddForce|AddTorque|velocity|angularVelocity|MovePosition|MoveRotation)\b",  # noqa: E501
        body,
        re.IGNORECASE,
    )
    if not m:
        return []
    line = _line_number(content, span[0] + m.start())
    return [
        _emit(
            file_path,
            line,
            content,
            rule_id="UN010",
            category="Performance",
            severity="warning",
            message="Rigidbody force/velocity set in Update - physics should run in FixedUpdate to avoid frame-rate jitter.",  # noqa: E501
            fix_suggestion="Move Rigidbody modifications to FixedUpdate(); scale forces with Time.fixedDeltaTime.",  # noqa: E501
        )
    ]


def detect_transform_in_loop(content: str, file_path: str) -> List[Issue]:
    """UN011: transform.position/rotation written inside a loop - each write notifies the physics engine."""  # noqa: E501
    out: List[Issue] = []
    loop_re = re.compile(r"\b(?:for|foreach|while)\s*\(")
    for loop in loop_re.finditer(content):
        brace_open = content.find("{", loop.end())
        if brace_open < 0 or brace_open - loop.end() > 200:
            continue
        depth, end = 0, brace_open
        for i in range(brace_open, len(content)):
            if content[i] == "{":
                depth += 1
            elif content[i] == "}":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        body_region = content[brace_open + 1 : end]
        m = re.search(
            r"\btransform\s*\.\s*(?:position|rotation|localPosition|localScale|eulerAngles)\s*=",  # noqa: E501
            body_region,
        )
        if not m:
            continue
        line = _line_number(content, brace_open + 1 + m.start())
        out.append(
            _emit(
                file_path,
                line,
                content,
                rule_id="UN011",
                category="Performance",
                severity="warning",
                message="transform.position/rotation assigned inside a loop - each write triggers a physics sync notification.",  # noqa: E501
                fix_suggestion="Compute the final transform outside the loop and assign once; batch with TransformPoint for arrays.",  # noqa: E501
            )
        )
    return out


def detect_tag_string_compare(content: str, file_path: str) -> List[Issue]:
    """UN012: `obj.tag == "X"` - boxes a string each call. Use CompareTag.

    Unity's GameObject.tag getter allocates a new managed string every
    access; equality with a literal allocates again. CompareTag avoids
    both allocations and is recommended by Unity's own profiler docs.
    """
    out: List[Issue] = []
    # \b matches after a `.` (non-word char) so `obj.tag == "X"` and
    # bare `tag == "X"` (implicit `this.tag`) are both caught.
    pattern = re.compile(r"\btag\s*(?:==|!=)\s*\"[^\"]+\"")
    for m in pattern.finditer(content):
        line = _line_number(content, m.start())
        out.append(
            _emit(
                file_path,
                line,
                content,
                rule_id="UN012",
                category="Performance",
                severity="warning",
                message="String comparison with .tag allocates per access - use CompareTag instead.",  # noqa: E501
                fix_suggestion='Replace `obj.tag == "X"` with `obj.CompareTag("X")`.',
            )
        )
    return out


def detect_missing_require_component(content: str, file_path: str) -> List[Issue]:
    """UN013: GetComponent<T> in Awake without [RequireComponent(typeof(T))] - dependency unchecked at edit-time."""  # noqa: E501
    awake_span = _find_method_body(
        content, r"\b(?:private|public|protected)?\s*void\s+Awake\s*\(\s*\)"
    )
    if not awake_span:
        return []
    awake_body = content[awake_span[0] : awake_span[1]]
    out: List[Issue] = []
    for m in re.finditer(r"\bGetComponent\s*<(\w+)>\s*\(\s*\)", awake_body):
        comp_type = m.group(1)
        if re.search(
            rf"\[RequireComponent\s*\(\s*typeof\s*\(\s*{re.escape(comp_type)}\s*\)",
            content[: awake_span[0]],
        ):
            continue
        line = _line_number(content, awake_span[0] + m.start())
        out.append(
            _emit(
                file_path,
                line,
                content,
                rule_id="UN013",
                category="BestPractices",
                severity="info",
                message=f"GetComponent<{comp_type}>() in Awake without [RequireComponent] - missing component causes silent null.",  # noqa: E501
                fix_suggestion=f"Add `[RequireComponent(typeof({comp_type}))]` above the class declaration.",  # noqa: E501
            )
        )
    return out


def detect_dont_destroy_non_singleton(content: str, file_path: str) -> List[Issue]:
    """UN014: DontDestroyOnLoad outside a singleton guard - duplicate instances accumulate on scene reload."""  # noqa: E501
    out: List[Issue] = []
    for m in re.finditer(r"\bDontDestroyOnLoad\s*\(", content):
        preceding = content[max(0, m.start() - 300) : m.start()]
        if re.search(r"\bif\s*\([^)]*\b_?[Ii]nstance\b[^)]*==\s*null", preceding):
            continue
        line = _line_number(content, m.start())
        out.append(
            _emit(
                file_path,
                line,
                content,
                rule_id="UN014",
                category="BestPractices",
                severity="warning",
                message="DontDestroyOnLoad called without a singleton guard - duplicates accumulate across scene loads.",  # noqa: E501
                fix_suggestion="Wrap in `if (instance == null) { instance = this; DontDestroyOnLoad(gameObject); } else { Destroy(gameObject); }`.",  # noqa: E501
            )
        )
    return out


def detect_resources_load(content: str, file_path: str) -> List[Issue]:
    """UN015: Resources.Load usage - synchronous, loads assets into always-resident memory; prefer Addressables."""  # noqa: E501
    out: List[Issue] = []
    for m in re.finditer(r"\bResources\.(?:Load|LoadAll|LoadAsync)\s*[<(]", content):
        line = _line_number(content, m.start())
        out.append(
            _emit(
                file_path,
                line,
                content,
                rule_id="UN015",
                category="BestPractices",
                severity="info",
                message="Resources.Load bundles all assets unconditionally and loads synchronously - prefer Addressables for on-demand async loading.",  # noqa: E501
                fix_suggestion='Migrate to `Addressables.LoadAssetAsync<T>("key")` with `.Completed` callback or `await`.',  # noqa: E501
            )
        )
    return out


def detect_scriptableobject_no_menu(content: str, file_path: str) -> List[Issue]:
    """UN016: ScriptableObject subclass without [CreateAssetMenu] - cannot be created from the Unity Editor."""  # noqa: E501
    so_match = re.search(r"\bclass\s+(\w+)\s*:\s*ScriptableObject\b", content)
    if not so_match:
        return []
    if re.search(r"\[CreateAssetMenu\b", content[: so_match.start()]):
        return []
    line = _line_number(content, so_match.start())
    return [
        _emit(
            file_path,
            line,
            content,
            rule_id="UN016",
            category="BestPractices",
            severity="info",
            message=f"ScriptableObject '{so_match.group(1)}' has no [CreateAssetMenu] - cannot be instantiated from Assets > Create.",  # noqa: E501
            fix_suggestion=f'Add `[CreateAssetMenu(fileName = "{so_match.group(1)}", menuName = "ScriptableObjects/{so_match.group(1)}")]` above the class.',  # noqa: E501
        )
    ]
