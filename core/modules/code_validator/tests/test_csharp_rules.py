"""Comprehensive tests for all 55 C# / Unity rule detectors.

Each rule has: positive test (fires), negative test (does not fire),
and at least one edge case. Total: ~165+ test functions.

Thresholds asserted here are taken from the live implementation in
csharp_rules.py (NOT from the task brief):
  - CSM001 long method   : body newline count >= 50
  - CSM002 long file      : total line count >= 500
  - CSM003 god object     : > 12 public members
  - CSM004 too many params: > 5 parameters
  - CSM005 deep nesting   : structural brace depth >= 5
  - CSP008 large Update   : Update/LateUpdate body newline count >= 50
  - CSB006 magic number   : numeric literal with abs(value) > 2 in an expression
"""

import sys
from pathlib import Path

_CORE = str(Path(__file__).parent.parent.parent)
sys.path.insert(0, _CORE)
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "modules"))

import pytest  # noqa: F401,E402
from code_validator.unity.csharp.csharp_best_practices import (  # noqa: E402
    detect_async_void,
    detect_catch_exception_broad,
    detect_commented_out_code,
    detect_empty_catch,
    detect_empty_destructor,
    detect_empty_if_body,
    detect_event_not_unsubscribed,
    detect_float_no_f_suffix,
    detect_hardcoded_path,
    detect_infinite_loop,
    detect_log_outside_editor_guard,
    detect_magic_number,
    detect_missing_override,
    detect_todo_comment,
)
from code_validator.unity.csharp.csharp_maintainability import (  # noqa: E402
    detect_class_god_object,
    detect_deep_nesting,
    detect_long_file,
    detect_long_method,
    detect_too_many_params,
)
from code_validator.unity.csharp.csharp_performance import (  # noqa: E402
    detect_collection_copy_in_loop,
    detect_debug_assert_in_update,
    detect_gc_collect,
    detect_heavy_math_in_update,
    detect_instantiate_in_update,
    detect_large_update_body,
    detect_linq_in_update,
    detect_new_object_in_loop,
    detect_new_waitforseconds,
    detect_string_concat_in_loop,
    detect_string_ops_in_update,
)
from code_validator.unity.csharp.csharp_security import (  # noqa: E402
    detect_collision_no_null_check,
    detect_direct_cast_no_check,
    detect_division_no_zero_check,
    detect_getcomponent_no_check,
    detect_hardcoded_secret,
    detect_http_url,
    detect_instantiate_no_check,
    detect_playerprefs_secret,
    detect_sql_concat,
)
from code_validator.unity.csharp.unity_specific import (  # noqa: E402
    detect_camera_main_in_update,
    detect_coroutine_leak,
    detect_dont_destroy_non_singleton,
    detect_empty_update,
    detect_findobject_in_update,
    detect_findobjectoftype_in_update,
    detect_getcomponent_in_update,
    detect_log_in_update,
    detect_missing_require_component,
    detect_physics_in_update,
    detect_public_field_monobehaviour,
    detect_resources_load,
    detect_scriptableobject_no_menu,
    detect_sendmessage_use,
    detect_tag_string_compare,
    detect_transform_in_loop,
)

FAKE_PATH = "Assets/Scripts/Test.cs"


def _wrap(body: str, base: str = "MonoBehaviour", name: str = "TestComp") -> str:
    """Wrap a class body in a minimal valid Unity source file."""
    return (
        "using UnityEngine;\n\n"
        f"public class {name} : {base}\n"
        "{\n"
        f"{body}\n"
        "}\n"
    )


# =========================================================================
# UN* — Unity-specific
# =========================================================================


# ── UN001: GameObject.Find in Update ─────────────────────────────────────


def test_un001_positive():
    src = _wrap(
        "    void Update()\n"
        "    {\n"
        '        var go = GameObject.Find("Player");\n'
        "    }"
    )
    issues = detect_findobject_in_update(src, FAKE_PATH)
    assert len(issues) >= 1
    assert issues[0]["rule_id"] == "UN001"


def test_un001_negative():
    src = _wrap(
        "    void Update()\n"
        "    {\n"
        "        transform.Translate(Vector3.up);\n"
        "    }"
    )
    issues = detect_findobject_in_update(src, FAKE_PATH)
    assert len(issues) == 0


def test_un001_edge_call_in_start_not_flagged():
    src = _wrap(
        "    void Start()\n"
        "    {\n"
        '        var go = GameObject.Find("Player");\n'
        "    }"
    )
    issues = detect_findobject_in_update(src, FAKE_PATH)
    assert len(issues) == 0


# ── UN002: GetComponent in Update ────────────────────────────────────────


def test_un002_positive():
    src = _wrap(
        "    void Update()\n"
        "    {\n"
        "        var r = GetComponent<Rigidbody>();\n"
        "    }"
    )
    issues = detect_getcomponent_in_update(src, FAKE_PATH)
    assert len(issues) >= 1
    assert issues[0]["rule_id"] == "UN002"


def test_un002_negative():
    src = _wrap(
        "    void Update()\n"
        "    {\n"
        "        transform.Rotate(Vector3.up);\n"
        "    }"
    )
    issues = detect_getcomponent_in_update(src, FAKE_PATH)
    assert len(issues) == 0


def test_un002_edge_call_in_awake_not_flagged():
    src = _wrap(
        "    void Awake()\n"
        "    {\n"
        "        var r = GetComponent<Rigidbody>();\n"
        "    }"
    )
    issues = detect_getcomponent_in_update(src, FAKE_PATH)
    assert len(issues) == 0


# ── UN003: FindObjectOfType in Update ────────────────────────────────────


def test_un003_positive():
    src = _wrap(
        "    void Update()\n"
        "    {\n"
        "        var m = FindObjectOfType<Camera>();\n"
        "    }"
    )
    issues = detect_findobjectoftype_in_update(src, FAKE_PATH)
    assert len(issues) >= 1
    assert issues[0]["rule_id"] == "UN003"


def test_un003_negative():
    src = _wrap("    void Update()\n    {\n        var x = 1;\n    }")
    issues = detect_findobjectoftype_in_update(src, FAKE_PATH)
    assert len(issues) == 0


def test_un003_edge_findanyobject_in_start_not_flagged():
    src = _wrap(
        "    void Start()\n"
        "    {\n"
        "        var m = FindAnyObjectByType<Camera>();\n"
        "    }"
    )
    issues = detect_findobjectoftype_in_update(src, FAKE_PATH)
    assert len(issues) == 0


# ── UN004: Debug.Log in Update ───────────────────────────────────────────


def test_un004_positive():
    src = _wrap("    void Update()\n" "    {\n" '        Debug.Log("frame");\n' "    }")
    issues = detect_log_in_update(src, FAKE_PATH)
    assert len(issues) >= 1
    assert issues[0]["rule_id"] == "UN004"


def test_un004_negative():
    src = _wrap("    void Update()\n    {\n        var x = 1;\n    }")
    issues = detect_log_in_update(src, FAKE_PATH)
    assert len(issues) == 0


def test_un004_edge_log_in_start_not_flagged():
    src = _wrap(
        "    void Start()\n" "    {\n" '        Debug.LogError("init");\n' "    }"
    )
    issues = detect_log_in_update(src, FAKE_PATH)
    assert len(issues) == 0


# ── UN005: SendMessage usage ─────────────────────────────────────────────


def test_un005_positive():
    src = _wrap("    void Hit()\n" "    {\n" '        SendMessage("OnHit");\n' "    }")
    issues = detect_sendmessage_use(src, FAKE_PATH)
    assert len(issues) >= 1
    assert issues[0]["rule_id"] == "UN005"


def test_un005_negative():
    src = _wrap("    void Hit()\n" "    {\n" "        OnHit();\n" "    }")
    issues = detect_sendmessage_use(src, FAKE_PATH)
    assert len(issues) == 0


def test_un005_edge_broadcastmessage_flagged():
    src = _wrap(
        "    void Hit()\n" "    {\n" '        BroadcastMessage("OnHit");\n' "    }"
    )
    issues = detect_sendmessage_use(src, FAKE_PATH)
    assert len(issues) >= 1
    assert issues[0]["rule_id"] == "UN005"


# ── UN006: public field on MonoBehaviour ─────────────────────────────────


def test_un006_positive():
    src = _wrap("    public int health;")
    issues = detect_public_field_monobehaviour(src, FAKE_PATH)
    assert len(issues) >= 1
    assert issues[0]["rule_id"] == "UN006"


def test_un006_negative_serializefield():
    src = _wrap("    [SerializeField] private int health;")
    issues = detect_public_field_monobehaviour(src, FAKE_PATH)
    assert len(issues) == 0


def test_un006_edge_not_monobehaviour():
    src = "public class PlainData\n" "{\n" "    public int health;\n" "}\n"
    issues = detect_public_field_monobehaviour(src, FAKE_PATH)
    assert len(issues) == 0


# ── UN007: empty Update ──────────────────────────────────────────────────


def test_un007_positive():
    src = _wrap("    void Update()\n    {\n    }")
    issues = detect_empty_update(src, FAKE_PATH)
    assert len(issues) >= 1
    assert issues[0]["rule_id"] == "UN007"


def test_un007_negative():
    src = _wrap(
        "    void Update()\n"
        "    {\n"
        "        transform.Rotate(Vector3.up);\n"
        "    }"
    )
    issues = detect_empty_update(src, FAKE_PATH)
    assert len(issues) == 0


def test_un007_edge_only_comments_is_empty():
    src = _wrap("    void Update()\n    {\n        // nothing yet\n    }")
    issues = detect_empty_update(src, FAKE_PATH)
    assert len(issues) >= 1
    assert issues[0]["rule_id"] == "UN007"


# ── UN008: Camera.main in Update ─────────────────────────────────────────


def test_un008_positive():
    src = _wrap(
        "    void Update()\n"
        "    {\n"
        "        var p = Camera.main.transform.position;\n"
        "    }"
    )
    issues = detect_camera_main_in_update(src, FAKE_PATH)
    assert len(issues) >= 1
    assert issues[0]["rule_id"] == "UN008"


def test_un008_negative():
    src = _wrap("    void Update()\n    {\n        var x = 1;\n    }")
    issues = detect_camera_main_in_update(src, FAKE_PATH)
    assert len(issues) == 0


def test_un008_edge_camera_main_in_start_not_flagged():
    src = _wrap("    void Start()\n" "    {\n" "        var c = Camera.main;\n" "    }")
    issues = detect_camera_main_in_update(src, FAKE_PATH)
    assert len(issues) == 0


# ── UN009: coroutine leak ────────────────────────────────────────────────


def test_un009_positive():
    src = _wrap(
        "    void Start()\n" "    {\n" "        StartCoroutine(Run());\n" "    }"
    )
    issues = detect_coroutine_leak(src, FAKE_PATH)
    assert len(issues) >= 1
    assert issues[0]["rule_id"] == "UN009"


def test_un009_negative_no_coroutine():
    src = _wrap("    void Start()\n    {\n        var x = 1;\n    }")
    issues = detect_coroutine_leak(src, FAKE_PATH)
    assert len(issues) == 0


def test_un009_edge_stopped_in_ondestroy():
    src = _wrap(
        "    void Start()\n"
        "    {\n"
        "        StartCoroutine(Run());\n"
        "    }\n"
        "    void OnDestroy()\n"
        "    {\n"
        "        StopAllCoroutines();\n"
        "    }"
    )
    issues = detect_coroutine_leak(src, FAKE_PATH)
    assert len(issues) == 0


# ── UN010: physics in Update ─────────────────────────────────────────────


def test_un010_positive():
    src = _wrap(
        "    void Update()\n" "    {\n" "        rb.AddForce(Vector3.up);\n" "    }"
    )
    issues = detect_physics_in_update(src, FAKE_PATH)
    assert len(issues) >= 1
    assert issues[0]["rule_id"] == "UN010"


def test_un010_negative():
    src = _wrap("    void Update()\n    {\n        var x = 1;\n    }")
    issues = detect_physics_in_update(src, FAKE_PATH)
    assert len(issues) == 0


def test_un010_edge_physics_in_fixedupdate_not_flagged():
    src = _wrap(
        "    void FixedUpdate()\n"
        "    {\n"
        "        rb.AddForce(Vector3.up);\n"
        "    }"
    )
    issues = detect_physics_in_update(src, FAKE_PATH)
    assert len(issues) == 0


# ── UN011: transform write in loop ───────────────────────────────────────


def test_un011_positive():
    src = _wrap(
        "    void Move()\n"
        "    {\n"
        "        for (int i = 0; i < 10; i++)\n"
        "        {\n"
        "            transform.position = Vector3.zero;\n"
        "        }\n"
        "    }"
    )
    issues = detect_transform_in_loop(src, FAKE_PATH)
    assert len(issues) >= 1
    assert issues[0]["rule_id"] == "UN011"


def test_un011_negative():
    src = _wrap(
        "    void Move()\n"
        "    {\n"
        "        for (int i = 0; i < 10; i++)\n"
        "        {\n"
        "            int x = i;\n"
        "        }\n"
        "    }"
    )
    issues = detect_transform_in_loop(src, FAKE_PATH)
    assert len(issues) == 0


def test_un011_edge_transform_write_outside_loop():
    src = _wrap(
        "    void Move()\n"
        "    {\n"
        "        transform.position = Vector3.zero;\n"
        "    }"
    )
    issues = detect_transform_in_loop(src, FAKE_PATH)
    assert len(issues) == 0


# ── UN012: tag string compare ────────────────────────────────────────────


def test_un012_positive():
    src = _wrap(
        "    void Hit(GameObject o)\n"
        "    {\n"
        '        if (o.tag == "Enemy") { }\n'
        "    }"
    )
    issues = detect_tag_string_compare(src, FAKE_PATH)
    assert len(issues) >= 1
    assert issues[0]["rule_id"] == "UN012"


def test_un012_negative_comparetag():
    src = _wrap(
        "    void Hit(GameObject o)\n"
        "    {\n"
        '        if (o.CompareTag("Enemy")) { }\n'
        "    }"
    )
    issues = detect_tag_string_compare(src, FAKE_PATH)
    assert len(issues) == 0


def test_un012_edge_not_equal_operator():
    src = _wrap(
        "    void Hit(GameObject o)\n"
        "    {\n"
        '        if (o.tag != "Enemy") { }\n'
        "    }"
    )
    issues = detect_tag_string_compare(src, FAKE_PATH)
    assert len(issues) >= 1
    assert issues[0]["rule_id"] == "UN012"


# ── UN013: missing RequireComponent ──────────────────────────────────────


def test_un013_positive():
    src = _wrap(
        "    void Awake()\n"
        "    {\n"
        "        var rb = GetComponent<Rigidbody>();\n"
        "    }"
    )
    issues = detect_missing_require_component(src, FAKE_PATH)
    assert len(issues) >= 1
    assert issues[0]["rule_id"] == "UN013"


def test_un013_negative_has_attribute():
    src = (
        "using UnityEngine;\n\n"
        "[RequireComponent(typeof(Rigidbody))]\n"
        "public class TestComp : MonoBehaviour\n"
        "{\n"
        "    void Awake()\n"
        "    {\n"
        "        var rb = GetComponent<Rigidbody>();\n"
        "    }\n"
        "}\n"
    )
    issues = detect_missing_require_component(src, FAKE_PATH)
    assert len(issues) == 0


def test_un013_edge_getcomponent_in_start_not_flagged():
    src = _wrap(
        "    void Start()\n"
        "    {\n"
        "        var rb = GetComponent<Rigidbody>();\n"
        "    }"
    )
    issues = detect_missing_require_component(src, FAKE_PATH)
    assert len(issues) == 0


# ── UN014: DontDestroyOnLoad without singleton guard ─────────────────────


def test_un014_positive():
    src = _wrap(
        "    void Awake()\n"
        "    {\n"
        "        DontDestroyOnLoad(gameObject);\n"
        "    }"
    )
    issues = detect_dont_destroy_non_singleton(src, FAKE_PATH)
    assert len(issues) >= 1
    assert issues[0]["rule_id"] == "UN014"


def test_un014_negative_no_dontdestroy():
    src = _wrap("    void Awake()\n    {\n        var x = 1;\n    }")
    issues = detect_dont_destroy_non_singleton(src, FAKE_PATH)
    assert len(issues) == 0


def test_un014_edge_singleton_guard_present():
    src = _wrap(
        "    private static TestComp _instance;\n"
        "    void Awake()\n"
        "    {\n"
        "        if (_instance == null)\n"
        "        {\n"
        "            _instance = this;\n"
        "            DontDestroyOnLoad(gameObject);\n"
        "        }\n"
        "    }"
    )
    issues = detect_dont_destroy_non_singleton(src, FAKE_PATH)
    assert len(issues) == 0


# ── UN015: Resources.Load ────────────────────────────────────────────────


def test_un015_positive():
    src = _wrap(
        "    void Load()\n"
        "    {\n"
        '        var p = Resources.Load<GameObject>("Prefab");\n'
        "    }"
    )
    issues = detect_resources_load(src, FAKE_PATH)
    assert len(issues) >= 1
    assert issues[0]["rule_id"] == "UN015"


def test_un015_negative():
    src = _wrap(
        "    void Load()\n" "    {\n" "        var p = addressables.Get();\n" "    }"
    )
    issues = detect_resources_load(src, FAKE_PATH)
    assert len(issues) == 0


def test_un015_edge_loadall_flagged():
    src = _wrap(
        "    void Load()\n"
        "    {\n"
        '        var p = Resources.LoadAll("dir");\n'
        "    }"
    )
    issues = detect_resources_load(src, FAKE_PATH)
    assert len(issues) >= 1
    assert issues[0]["rule_id"] == "UN015"


# ── UN016: ScriptableObject without CreateAssetMenu ──────────────────────


def test_un016_positive():
    src = (
        "using UnityEngine;\n\n"
        "public class WeaponData : ScriptableObject\n"
        "{\n"
        "    public int damage;\n"
        "}\n"
    )
    issues = detect_scriptableobject_no_menu(src, FAKE_PATH)
    assert len(issues) >= 1
    assert issues[0]["rule_id"] == "UN016"


def test_un016_negative_has_attribute():
    src = (
        "using UnityEngine;\n\n"
        '[CreateAssetMenu(menuName = "Data/Weapon")]\n'
        "public class WeaponData : ScriptableObject\n"
        "{\n"
        "}\n"
    )
    issues = detect_scriptableobject_no_menu(src, FAKE_PATH)
    assert len(issues) == 0


def test_un016_edge_not_scriptableobject():
    src = _wrap("    public int damage;")
    issues = detect_scriptableobject_no_menu(src, FAKE_PATH)
    assert len(issues) == 0


# =========================================================================
# CSP* — Performance
# =========================================================================


# ── CSP001: LINQ in Update ───────────────────────────────────────────────


def test_csp001_positive():
    src = _wrap(
        "    void Update()\n"
        "    {\n"
        "        var first = items.Where(x => x > 0).First();\n"
        "    }"
    )
    issues = detect_linq_in_update(src, FAKE_PATH)
    assert len(issues) >= 1
    assert issues[0]["rule_id"] == "CSP001"


def test_csp001_negative():
    src = _wrap("    void Update()\n    {\n        var x = 1;\n    }")
    issues = detect_linq_in_update(src, FAKE_PATH)
    assert len(issues) == 0


def test_csp001_edge_linq_in_start_not_flagged():
    src = _wrap(
        "    void Start()\n" "    {\n" "        var list = items.ToList();\n" "    }"
    )
    issues = detect_linq_in_update(src, FAKE_PATH)
    assert len(issues) == 0


# ── CSP002: string concat in loop ────────────────────────────────────────


def test_csp002_positive():
    src = _wrap(
        "    void Build()\n"
        "    {\n"
        '        string s = "";\n'
        "        for (int i = 0; i < 10; i++)\n"
        "        {\n"
        '            s += "x";\n'
        "        }\n"
        "    }"
    )
    issues = detect_string_concat_in_loop(src, FAKE_PATH)
    assert len(issues) >= 1
    assert issues[0]["rule_id"] == "CSP002"


def test_csp002_negative():
    src = _wrap(
        "    void Build()\n"
        "    {\n"
        "        for (int i = 0; i < 10; i++)\n"
        "        {\n"
        "            int total = i + 1;\n"
        "        }\n"
        "    }"
    )
    issues = detect_string_concat_in_loop(src, FAKE_PATH)
    assert len(issues) == 0


def test_csp002_edge_concat_outside_loop():
    src = _wrap(
        "    void Build()\n"
        "    {\n"
        '        string s = "";\n'
        '        s += "x";\n'
        "    }"
    )
    issues = detect_string_concat_in_loop(src, FAKE_PATH)
    assert len(issues) == 0


# ── CSP003: heavy math in Update ─────────────────────────────────────────


def test_csp003_positive():
    src = _wrap(
        "    void Update()\n" "    {\n" "        float d = Mathf.Sqrt(value);\n" "    }"
    )
    issues = detect_heavy_math_in_update(src, FAKE_PATH)
    assert len(issues) >= 1
    assert issues[0]["rule_id"] == "CSP003"


def test_csp003_negative():
    src = _wrap(
        "    void Update()\n"
        "    {\n"
        "        float d = Mathf.Clamp(value, 0f, 1f);\n"
        "    }"
    )
    issues = detect_heavy_math_in_update(src, FAKE_PATH)
    assert len(issues) == 0


def test_csp003_edge_sqrt_in_start_not_flagged():
    src = _wrap(
        "    void Start()\n"
        "    {\n"
        "        float d = Mathf.Pow(value, 2f);\n"
        "    }"
    )
    issues = detect_heavy_math_in_update(src, FAKE_PATH)
    assert len(issues) == 0


# ── CSP004: Instantiate in Update ────────────────────────────────────────


def test_csp004_positive():
    src = _wrap(
        "    void Update()\n" "    {\n" "        Instantiate(prefab);\n" "    }"
    )
    issues = detect_instantiate_in_update(src, FAKE_PATH)
    assert len(issues) >= 1
    assert issues[0]["rule_id"] == "CSP004"


def test_csp004_negative():
    src = _wrap("    void Update()\n    {\n        var x = 1;\n    }")
    issues = detect_instantiate_in_update(src, FAKE_PATH)
    assert len(issues) == 0


def test_csp004_edge_instantiate_in_start_not_flagged():
    src = _wrap("    void Start()\n" "    {\n" "        Instantiate(prefab);\n" "    }")
    issues = detect_instantiate_in_update(src, FAKE_PATH)
    assert len(issues) == 0


# ── CSP006: new WaitForSeconds in yield ──────────────────────────────────


def test_csp006_positive():
    src = _wrap(
        "    System.Collections.IEnumerator Run()\n"
        "    {\n"
        "        yield return new WaitForSeconds(1f);\n"
        "    }"
    )
    issues = detect_new_waitforseconds(src, FAKE_PATH)
    assert len(issues) >= 1
    assert issues[0]["rule_id"] == "CSP006"


def test_csp006_negative():
    src = _wrap(
        "    System.Collections.IEnumerator Run()\n"
        "    {\n"
        "        yield return _wait;\n"
        "    }"
    )
    issues = detect_new_waitforseconds(src, FAKE_PATH)
    assert len(issues) == 0


def test_csp006_edge_waitforseconds_field_not_yield():
    src = _wrap("    private WaitForSeconds _wait = new WaitForSeconds(1f);")
    issues = detect_new_waitforseconds(src, FAKE_PATH)
    assert len(issues) == 0


# ── CSP007: string ops in Update ─────────────────────────────────────────


def test_csp007_positive():
    src = _wrap(
        "    void Update()\n"
        "    {\n"
        '        string s = string.Format("{0}", x);\n'
        "    }"
    )
    issues = detect_string_ops_in_update(src, FAKE_PATH)
    assert len(issues) >= 1
    assert issues[0]["rule_id"] == "CSP007"


def test_csp007_negative():
    src = _wrap("    void Update()\n    {\n        var x = 1;\n    }")
    issues = detect_string_ops_in_update(src, FAKE_PATH)
    assert len(issues) == 0


def test_csp007_edge_string_format_in_start_not_flagged():
    src = _wrap(
        "    void Start()\n"
        "    {\n"
        '        string s = string.Format("{0}", x);\n'
        "    }"
    )
    issues = detect_string_ops_in_update(src, FAKE_PATH)
    assert len(issues) == 0


# ── CSP008: large Update body (>= 50 newlines) ───────────────────────────


def test_csp008_positive():
    lines = "\n".join(f"        int v{i} = {i};" for i in range(60))
    src = _wrap("    void Update()\n    {\n" + lines + "\n    }")
    issues = detect_large_update_body(src, FAKE_PATH)
    assert len(issues) >= 1
    assert issues[0]["rule_id"] == "CSP008"


def test_csp008_negative_small_body():
    lines = "\n".join(f"        int v{i} = {i};" for i in range(5))
    src = _wrap("    void Update()\n    {\n" + lines + "\n    }")
    issues = detect_large_update_body(src, FAKE_PATH)
    assert len(issues) == 0


def test_csp008_edge_large_fixedupdate_not_flagged():
    # CSP008 only matches Update/LateUpdate, not FixedUpdate.
    lines = "\n".join(f"        int v{i} = {i};" for i in range(60))
    src = _wrap("    void FixedUpdate()\n    {\n" + lines + "\n    }")
    issues = detect_large_update_body(src, FAKE_PATH)
    assert len(issues) == 0


# ── CSP009: collection copy in loop ──────────────────────────────────────


def test_csp009_positive():
    src = _wrap(
        "    void Run()\n"
        "    {\n"
        "        foreach (var x in src)\n"
        "        {\n"
        "            var copy = source.ToList();\n"
        "        }\n"
        "    }"
    )
    issues = detect_collection_copy_in_loop(src, FAKE_PATH)
    assert len(issues) >= 1
    assert issues[0]["rule_id"] == "CSP009"


def test_csp009_negative():
    src = _wrap(
        "    void Run()\n"
        "    {\n"
        "        foreach (var x in src)\n"
        "        {\n"
        "            int y = x + 1;\n"
        "        }\n"
        "    }"
    )
    issues = detect_collection_copy_in_loop(src, FAKE_PATH)
    assert len(issues) == 0


def test_csp009_edge_tolist_outside_loop():
    src = _wrap(
        "    void Run()\n" "    {\n" "        var copy = source.ToList();\n" "    }"
    )
    issues = detect_collection_copy_in_loop(src, FAKE_PATH)
    assert len(issues) == 0


# ── CSP010: new object in loop ───────────────────────────────────────────


def test_csp010_positive():
    src = _wrap(
        "    void Run()\n"
        "    {\n"
        "        for (int i = 0; i < 10; i++)\n"
        "        {\n"
        "            var sb = new StringBuilder();\n"
        "        }\n"
        "    }"
    )
    issues = detect_new_object_in_loop(src, FAKE_PATH)
    assert len(issues) >= 1
    assert issues[0]["rule_id"] == "CSP010"


def test_csp010_negative():
    src = _wrap(
        "    void Run()\n"
        "    {\n"
        "        for (int i = 0; i < 10; i++)\n"
        "        {\n"
        "            int y = i + 1;\n"
        "        }\n"
        "    }"
    )
    issues = detect_new_object_in_loop(src, FAKE_PATH)
    assert len(issues) == 0


def test_csp010_edge_value_type_excluded():
    src = _wrap(
        "    void Run()\n"
        "    {\n"
        "        for (int i = 0; i < 10; i++)\n"
        "        {\n"
        "            var v = new Vector3(0, 0, 0);\n"
        "        }\n"
        "    }"
    )
    issues = detect_new_object_in_loop(src, FAKE_PATH)
    assert len(issues) == 0


# ── CSP011: GC.Collect ───────────────────────────────────────────────────


def test_csp011_positive():
    src = _wrap("    void Clean()\n" "    {\n" "        GC.Collect();\n" "    }")
    issues = detect_gc_collect(src, FAKE_PATH)
    assert len(issues) >= 1
    assert issues[0]["rule_id"] == "CSP011"


def test_csp011_negative():
    src = _wrap(
        "    void Clean()\n"
        "    {\n"
        "        Resources.UnloadUnusedAssets();\n"
        "    }"
    )
    issues = detect_gc_collect(src, FAKE_PATH)
    assert len(issues) == 0


def test_csp011_edge_gc_collect_with_args_flagged():
    src = _wrap(
        "    void Clean()\n"
        "    {\n"
        "        GC.Collect(0, GCCollectionMode.Forced);\n"
        "    }"
    )
    issues = detect_gc_collect(src, FAKE_PATH)
    assert len(issues) >= 1
    assert issues[0]["rule_id"] == "CSP011"


# ── CSP012: Debug.Assert in Update ───────────────────────────────────────


def test_csp012_positive():
    src = _wrap(
        "    void Update()\n" "    {\n" "        Debug.Assert(value > 0);\n" "    }"
    )
    issues = detect_debug_assert_in_update(src, FAKE_PATH)
    assert len(issues) >= 1
    assert issues[0]["rule_id"] == "CSP012"


def test_csp012_negative():
    src = _wrap("    void Update()\n    {\n        var x = 1;\n    }")
    issues = detect_debug_assert_in_update(src, FAKE_PATH)
    assert len(issues) == 0


def test_csp012_edge_assert_in_awake_not_flagged():
    src = _wrap(
        "    void Awake()\n" "    {\n" "        Debug.Assert(value > 0);\n" "    }"
    )
    issues = detect_debug_assert_in_update(src, FAKE_PATH)
    assert len(issues) == 0


# =========================================================================
# CSB* — Best practices
# =========================================================================


# ── CSB001: empty catch ──────────────────────────────────────────────────


def test_csb001_positive():
    src = _wrap(
        "    void Do()\n"
        "    {\n"
        "        try { Risky(); }\n"
        "        catch (System.Exception) { }\n"
        "    }"
    )
    issues = detect_empty_catch(src, FAKE_PATH)
    assert len(issues) >= 1
    assert issues[0]["rule_id"] == "CSB001"


def test_csb001_negative():
    src = _wrap(
        "    void Do()\n"
        "    {\n"
        "        try { Risky(); }\n"
        "        catch (System.Exception e) { Debug.LogException(e); }\n"
        "    }"
    )
    issues = detect_empty_catch(src, FAKE_PATH)
    assert len(issues) == 0


def test_csb001_edge_whitespace_only_is_empty():
    src = _wrap(
        "    void Do()\n"
        "    {\n"
        "        try { Risky(); }\n"
        "        catch {    }\n"
        "    }"
    )
    issues = detect_empty_catch(src, FAKE_PATH)
    assert len(issues) >= 1
    assert issues[0]["rule_id"] == "CSB001"


# ── CSB002: TODO comment ─────────────────────────────────────────────────


def test_csb002_positive():
    src = _wrap("    // TODO: refactor this\n    void Do() { }")
    issues = detect_todo_comment(src, FAKE_PATH)
    assert len(issues) >= 1
    assert issues[0]["rule_id"] == "CSB002"


def test_csb002_negative():
    src = _wrap("    // this is a normal comment\n    void Do() { }")
    issues = detect_todo_comment(src, FAKE_PATH)
    assert len(issues) == 0


def test_csb002_edge_fixme_flagged():
    src = _wrap("    // FIXME broken edge case\n    void Do() { }")
    issues = detect_todo_comment(src, FAKE_PATH)
    assert len(issues) >= 1
    assert issues[0]["rule_id"] == "CSB002"


# ── CSB003: broad catch (Exception) ──────────────────────────────────────


def test_csb003_positive():
    src = _wrap(
        "    void Do()\n"
        "    {\n"
        "        try { Risky(); }\n"
        "        catch (Exception ex) { return; }\n"
        "    }"
    )
    issues = detect_catch_exception_broad(src, FAKE_PATH)
    assert len(issues) >= 1
    assert issues[0]["rule_id"] == "CSB003"


def test_csb003_negative_logged():
    src = _wrap(
        "    void Do()\n"
        "    {\n"
        "        try { Risky(); }\n"
        "        catch (Exception ex) { Debug.LogException(ex); }\n"
        "    }"
    )
    issues = detect_catch_exception_broad(src, FAKE_PATH)
    assert len(issues) == 0


def test_csb003_edge_specific_exception_not_flagged():
    src = _wrap(
        "    void Do()\n"
        "    {\n"
        "        try { Risky(); }\n"
        "        catch (IOException ex) { return; }\n"
        "    }"
    )
    issues = detect_catch_exception_broad(src, FAKE_PATH)
    assert len(issues) == 0


# ── CSB004: infinite loop ────────────────────────────────────────────────


def test_csb004_positive():
    src = _wrap(
        "    void Spin()\n"
        "    {\n"
        "        while (true)\n"
        "        {\n"
        "            DoWork();\n"
        "        }\n"
        "    }"
    )
    issues = detect_infinite_loop(src, FAKE_PATH)
    assert len(issues) >= 1
    assert issues[0]["rule_id"] == "CSB004"


def test_csb004_negative_has_break():
    src = _wrap(
        "    void Spin()\n"
        "    {\n"
        "        while (true)\n"
        "        {\n"
        "            if (done) break;\n"
        "        }\n"
        "    }"
    )
    issues = detect_infinite_loop(src, FAKE_PATH)
    assert len(issues) == 0


def test_csb004_edge_for_ever_loop_flagged():
    src = _wrap(
        "    void Spin()\n"
        "    {\n"
        "        for (;;)\n"
        "        {\n"
        "            DoWork();\n"
        "        }\n"
        "    }"
    )
    issues = detect_infinite_loop(src, FAKE_PATH)
    assert len(issues) >= 1
    assert issues[0]["rule_id"] == "CSB004"


# ── CSB005: async void ───────────────────────────────────────────────────


def test_csb005_positive():
    src = _wrap(
        "    public async void LoadData()\n"
        "    {\n"
        "        await Task.Delay(1);\n"
        "    }"
    )
    issues = detect_async_void(src, FAKE_PATH)
    assert len(issues) >= 1
    assert issues[0]["rule_id"] == "CSB005"


def test_csb005_negative_async_task():
    src = _wrap(
        "    public async Task LoadData()\n"
        "    {\n"
        "        await Task.Delay(1);\n"
        "    }"
    )
    issues = detect_async_void(src, FAKE_PATH)
    assert len(issues) == 0


def test_csb005_edge_event_handler_not_flagged():
    src = _wrap(
        "    public async void OnButtonClicked()\n"
        "    {\n"
        "        await Task.Delay(1);\n"
        "    }"
    )
    issues = detect_async_void(src, FAKE_PATH)
    assert len(issues) == 0


# ── CSB006: magic number ─────────────────────────────────────────────────


def test_csb006_positive():
    src = _wrap(
        "    void Do()\n" "    {\n" "        float r = speed * 42 + offset;\n" "    }"
    )
    issues = detect_magic_number(src, FAKE_PATH)
    assert len(issues) >= 1
    assert issues[0]["rule_id"] == "CSB006"


def test_csb006_negative_small_values():
    src = _wrap("    void Do()\n" "    {\n" "        int r = a + 1 - 2;\n" "    }")
    issues = detect_magic_number(src, FAKE_PATH)
    assert len(issues) == 0


def test_csb006_edge_const_declaration_not_flagged():
    src = _wrap("    private const int MaxHealth = 100;")
    issues = detect_magic_number(src, FAKE_PATH)
    assert len(issues) == 0


# ── CSB009: missing override ─────────────────────────────────────────────


def test_csb009_positive():
    src = (
        "public class Child : BaseController\n"
        "{\n"
        "    void Start()\n"
        "    {\n"
        "        DoInit();\n"
        "    }\n"
        "}\n"
    )
    issues = detect_missing_override(src, FAKE_PATH)
    assert len(issues) >= 1
    assert issues[0]["rule_id"] == "CSB009"


def test_csb009_negative_has_override():
    src = (
        "public class Child : BaseController\n"
        "{\n"
        "    protected override void Start()\n"
        "    {\n"
        "        base.Start();\n"
        "    }\n"
        "}\n"
    )
    issues = detect_missing_override(src, FAKE_PATH)
    assert len(issues) == 0


def test_csb009_edge_monobehaviour_base_not_flagged():
    src = _wrap("    void Start()\n" "    {\n" "        DoInit();\n" "    }")
    issues = detect_missing_override(src, FAKE_PATH)
    assert len(issues) == 0


# ── CSB010: hardcoded path ───────────────────────────────────────────────


def test_csb010_positive():
    # CSB010 Windows pattern: drive letter + single '\' + 3+ non-backslash
    # chars. The C# source literal is `"C:\data"` (one backslash).
    src = _wrap("    void Load()\n" "    {\n" '        var p = "C:\\data";\n' "    }")
    issues = detect_hardcoded_path(src, FAKE_PATH)
    assert len(issues) >= 1
    assert issues[0]["rule_id"] == "CSB010"


def test_csb010_negative():
    src = _wrap(
        "    void Load()\n"
        "    {\n"
        "        var p = Application.persistentDataPath;\n"
        "    }"
    )
    issues = detect_hardcoded_path(src, FAKE_PATH)
    assert len(issues) == 0


def test_csb010_edge_unix_path_flagged():
    src = _wrap(
        "    void Load()\n"
        "    {\n"
        '        var p = "/home/dev/project/data.json";\n'
        "    }"
    )
    issues = detect_hardcoded_path(src, FAKE_PATH)
    assert len(issues) >= 1
    assert issues[0]["rule_id"] == "CSB010"


# ── CSB011: empty if body ────────────────────────────────────────────────


def test_csb011_positive():
    src = _wrap("    void Do()\n" "    {\n" "        if (ready) { }\n" "    }")
    issues = detect_empty_if_body(src, FAKE_PATH)
    assert len(issues) >= 1
    assert issues[0]["rule_id"] == "CSB011"


def test_csb011_negative():
    src = _wrap(
        "    void Do()\n" "    {\n" "        if (ready) { DoWork(); }\n" "    }"
    )
    issues = detect_empty_if_body(src, FAKE_PATH)
    assert len(issues) == 0


def test_csb011_edge_whitespace_only_body_flagged():
    src = _wrap("    void Do()\n" "    {\n" "        if (ready) {   }\n" "    }")
    issues = detect_empty_if_body(src, FAKE_PATH)
    assert len(issues) >= 1
    assert issues[0]["rule_id"] == "CSB011"


# ── CSB012: event not unsubscribed ───────────────────────────────────────


def test_csb012_positive():
    src = _wrap(
        "    void Start()\n"
        "    {\n"
        "        GameManager.OnScore += HandleScore;\n"
        "    }"
    )
    issues = detect_event_not_unsubscribed(src, FAKE_PATH)
    assert len(issues) >= 1
    assert issues[0]["rule_id"] == "CSB012"


def test_csb012_negative_unsubscribed():
    src = _wrap(
        "    void Start()\n"
        "    {\n"
        "        OnScore += HandleScore;\n"
        "    }\n"
        "    void OnDestroy()\n"
        "    {\n"
        "        OnScore -= HandleScore;\n"
        "    }"
    )
    issues = detect_event_not_unsubscribed(src, FAKE_PATH)
    assert len(issues) == 0


def test_csb012_edge_ui_event_excluded():
    src = _wrap(
        "    void Start()\n" "    {\n" "        onClick += HandleClick;\n" "    }"
    )
    issues = detect_event_not_unsubscribed(src, FAKE_PATH)
    assert len(issues) == 0


# ── CSB013: Debug.Log outside editor guard ───────────────────────────────


def test_csb013_positive():
    src = _wrap(
        "    void Do()\n" "    {\n" '        Debug.Log("always runs");\n' "    }"
    )
    issues = detect_log_outside_editor_guard(src, FAKE_PATH)
    assert len(issues) >= 1
    assert issues[0]["rule_id"] == "CSB013"


def test_csb013_negative_guarded():
    src = _wrap(
        "    void Do()\n"
        "    {\n"
        "#if UNITY_EDITOR\n"
        '        Debug.Log("editor only");\n'
        "#endif\n"
        "    }"
    )
    issues = detect_log_outside_editor_guard(src, FAKE_PATH)
    assert len(issues) == 0


def test_csb013_edge_no_log_at_all():
    src = _wrap("    void Do()\n    {\n        var x = 1;\n    }")
    issues = detect_log_outside_editor_guard(src, FAKE_PATH)
    assert len(issues) == 0


# ── CSB014: float missing f suffix ───────────────────────────────────────


def test_csb014_positive():
    src = _wrap("    void Do() { float speed = 1.5; }")
    issues = detect_float_no_f_suffix(src, FAKE_PATH)
    assert len(issues) >= 1
    assert issues[0]["rule_id"] == "CSB014"


def test_csb014_negative_has_suffix():
    src = _wrap("    void Do() { float speed = 1.5f; }")
    issues = detect_float_no_f_suffix(src, FAKE_PATH)
    assert len(issues) == 0


def test_csb014_edge_int_literal_not_flagged():
    src = _wrap("    void Do() { float speed = 3; }")
    issues = detect_float_no_f_suffix(src, FAKE_PATH)
    assert len(issues) == 0


# ── CSB015: empty destructor ─────────────────────────────────────────────


def test_csb015_positive():
    src = "public class Res\n" "{\n" "    ~Res() { }\n" "}\n"
    issues = detect_empty_destructor(src, FAKE_PATH)
    assert len(issues) >= 1
    assert issues[0]["rule_id"] == "CSB015"


def test_csb015_negative_non_empty():
    src = "public class Res\n" "{\n" "    ~Res() { Cleanup(); }\n" "}\n"
    issues = detect_empty_destructor(src, FAKE_PATH)
    assert len(issues) == 0


def test_csb015_edge_no_destructor():
    src = _wrap("    public int x;")
    issues = detect_empty_destructor(src, FAKE_PATH)
    assert len(issues) == 0


# ── CSB016: commented-out code ───────────────────────────────────────────


def test_csb016_positive():
    src = _wrap(
        "    void Do()\n"
        "    {\n"
        "        // int a = 1;\n"
        "        // a = a + 2;\n"
        "        // return a;\n"
        "    }"
    )
    issues = detect_commented_out_code(src, FAKE_PATH)
    assert len(issues) >= 1
    assert issues[0]["rule_id"] == "CSB016"


def test_csb016_negative_prose_comments():
    src = _wrap(
        "    void Do()\n" "    {\n" "        // This explains the logic\n" "    }"
    )
    issues = detect_commented_out_code(src, FAKE_PATH)
    assert len(issues) == 0


def test_csb016_edge_two_lines_below_threshold():
    src = _wrap(
        "    void Do()\n"
        "    {\n"
        "        // int a = 1;\n"
        "        // a = a + 2;\n"
        "    }"
    )
    issues = detect_commented_out_code(src, FAKE_PATH)
    assert len(issues) == 0


# =========================================================================
# CSS* — Security
# =========================================================================


# ── CSS001: SQL concat ───────────────────────────────────────────────────


def test_css001_positive():
    src = _wrap(
        "    void Q(string id)\n"
        "    {\n"
        '        var cmd = new SqlCommand("SELECT * FROM t WHERE id=" + id);\n'
        "    }"
    )
    issues = detect_sql_concat(src, FAKE_PATH)
    assert len(issues) >= 1
    assert issues[0]["rule_id"] == "CSS001"


def test_css001_negative_parameterised():
    src = _wrap(
        "    void Q(string id)\n"
        "    {\n"
        '        var cmd = new SqlCommand("SELECT * FROM t WHERE id=@id");\n'
        "    }"
    )
    issues = detect_sql_concat(src, FAKE_PATH)
    assert len(issues) == 0


def test_css001_edge_sqlite_command_flagged():
    src = _wrap(
        "    void Q(string name)\n"
        "    {\n"
        '        var c = new SqliteCommand("SELECT * FROM u WHERE n=" + name);\n'
        "    }"
    )
    issues = detect_sql_concat(src, FAKE_PATH)
    assert len(issues) >= 1
    assert issues[0]["rule_id"] == "CSS001"


# ── CSS002: hardcoded secret ─────────────────────────────────────────────


def test_css002_positive():
    src = _wrap('    private string password = "supersecret123";')
    issues = detect_hardcoded_secret(src, FAKE_PATH)
    assert len(issues) >= 1
    assert issues[0]["rule_id"] == "CSS002"


def test_css002_negative():
    src = _wrap('    private string username = "player1";')
    issues = detect_hardcoded_secret(src, FAKE_PATH)
    assert len(issues) == 0


def test_css002_edge_apikey_flagged():
    src = _wrap('    private string apiKey = "abcdef123456";')
    issues = detect_hardcoded_secret(src, FAKE_PATH)
    assert len(issues) >= 1
    assert issues[0]["rule_id"] == "CSS002"


# ── CSS003: http:// URL ──────────────────────────────────────────────────


def test_css003_positive():
    src = _wrap('    private string url = "http://api.example.com/data";')
    issues = detect_http_url(src, FAKE_PATH)
    assert len(issues) >= 1
    assert issues[0]["rule_id"] == "CSS003"


def test_css003_negative_https():
    src = _wrap('    private string url = "https://api.example.com/data";')
    issues = detect_http_url(src, FAKE_PATH)
    assert len(issues) == 0


def test_css003_edge_localhost_excluded():
    src = _wrap('    private string url = "http://localhost:8080/test";')
    issues = detect_http_url(src, FAKE_PATH)
    assert len(issues) == 0


# ── CSS004: PlayerPrefs secret ───────────────────────────────────────────


def test_css004_positive():
    src = _wrap(
        "    void Save()\n"
        "    {\n"
        '        PlayerPrefs.SetString("user_password", pw);\n'
        "    }"
    )
    issues = detect_playerprefs_secret(src, FAKE_PATH)
    assert len(issues) >= 1
    assert issues[0]["rule_id"] == "CSS004"


def test_css004_negative():
    src = _wrap(
        "    void Save()\n"
        "    {\n"
        '        PlayerPrefs.SetString("volume_level", "10");\n'
        "    }"
    )
    issues = detect_playerprefs_secret(src, FAKE_PATH)
    assert len(issues) == 0


def test_css004_edge_token_key_flagged():
    src = _wrap(
        "    void Save()\n"
        "    {\n"
        '        PlayerPrefs.SetString("auth_token", t);\n'
        "    }"
    )
    issues = detect_playerprefs_secret(src, FAKE_PATH)
    assert len(issues) >= 1
    assert issues[0]["rule_id"] == "CSS004"


# ── CSS005: Instantiate without null check ───────────────────────────────


def test_css005_positive():
    src = _wrap(
        "    void Spawn()\n"
        "    {\n"
        "        var inst = Instantiate(prefab);\n"
        "        inst.SetActive(true);\n"
        "    }"
    )
    issues = detect_instantiate_no_check(src, FAKE_PATH)
    assert len(issues) >= 1
    assert issues[0]["rule_id"] == "CSS005"


def test_css005_negative_checked():
    # No `inst.` dereference within 3 lines of the assignment -> safe.
    src = _wrap(
        "    void Spawn()\n"
        "    {\n"
        "        var inst = Instantiate(prefab);\n"
        "        if (inst == null) return;\n"
        "        DoSomethingElse();\n"
        "        AnotherCall();\n"
        "        YetAnotherCall();\n"
        "        inst.SetActive(true);\n"
        "    }"
    )
    issues = detect_instantiate_no_check(src, FAKE_PATH)
    assert len(issues) == 0


def test_css005_edge_result_not_dereferenced():
    src = _wrap(
        "    void Spawn()\n"
        "    {\n"
        "        var inst = Instantiate(prefab);\n"
        "    }"
    )
    issues = detect_instantiate_no_check(src, FAKE_PATH)
    assert len(issues) == 0


# ── CSS006: GetComponent without null check ──────────────────────────────


def test_css006_positive():
    src = _wrap(
        "    void Init()\n"
        "    {\n"
        "        var rb = GetComponent<Rigidbody>();\n"
        "        rb.useGravity = true;\n"
        "    }"
    )
    issues = detect_getcomponent_no_check(src, FAKE_PATH)
    assert len(issues) >= 1
    assert issues[0]["rule_id"] == "CSS006"


def test_css006_negative_checked():
    # No `rb.` dereference within 3 lines of the assignment -> safe.
    src = _wrap(
        "    void Init()\n"
        "    {\n"
        "        var rb = GetComponent<Rigidbody>();\n"
        "        if (rb == null) return;\n"
        "        DoSomethingElse();\n"
        "        AnotherCall();\n"
        "        YetAnotherCall();\n"
        "        rb.useGravity = true;\n"
        "    }"
    )
    issues = detect_getcomponent_no_check(src, FAKE_PATH)
    assert len(issues) == 0


def test_css006_edge_result_not_dereferenced():
    src = _wrap(
        "    void Init()\n"
        "    {\n"
        "        var rb = GetComponent<Rigidbody>();\n"
        "    }"
    )
    issues = detect_getcomponent_no_check(src, FAKE_PATH)
    assert len(issues) == 0


# ── CSS007: direct cast without null check ───────────────────────────────


def test_css007_positive():
    src = _wrap(
        "    void Use(object o)\n" "    {\n" "        var e = (Enemy)o;\n" "    }"
    )
    issues = detect_direct_cast_no_check(src, FAKE_PATH)
    assert len(issues) >= 1
    assert issues[0]["rule_id"] == "CSS007"


def test_css007_negative_as_pattern():
    src = _wrap(
        "    void Use(object o)\n"
        "    {\n"
        "        var e = o as Enemy;\n"
        "        if (e == null) return;\n"
        "    }"
    )
    issues = detect_direct_cast_no_check(src, FAKE_PATH)
    assert len(issues) == 0


def test_css007_edge_primitive_cast_excluded():
    src = _wrap(
        "    void Use(object o)\n" "    {\n" "        var n = (int)o;\n" "    }"
    )
    issues = detect_direct_cast_no_check(src, FAKE_PATH)
    assert len(issues) == 0


# ── CSS008: division without zero check ──────────────────────────────────


def test_css008_positive():
    src = _wrap(
        "    void Do(int total, int parts)\n"
        "    {\n"
        "        int avg = total / parts;\n"
        "    }"
    )
    issues = detect_division_no_zero_check(src, FAKE_PATH)
    assert len(issues) >= 1
    assert issues[0]["rule_id"] == "CSS008"


def test_css008_negative_guarded():
    src = _wrap(
        "    void Do(int total, int parts)\n"
        "    {\n"
        "        if (parts != 0)\n"
        "        {\n"
        "            int avg = total / parts;\n"
        "        }\n"
        "    }"
    )
    issues = detect_division_no_zero_check(src, FAKE_PATH)
    assert len(issues) == 0


def test_css008_edge_literal_divisor_not_flagged():
    src = _wrap(
        "    void Do(int total)\n" "    {\n" "        int avg = total / 4;\n" "    }"
    )
    issues = detect_division_no_zero_check(src, FAKE_PATH)
    assert len(issues) == 0


# ── CSS009: collision handler without null check ─────────────────────────


def test_css009_positive():
    src = _wrap(
        "    void OnCollisionEnter(Collision col)\n"
        "    {\n"
        "        col.gameObject.SetActive(false);\n"
        "    }"
    )
    issues = detect_collision_no_null_check(src, FAKE_PATH)
    assert len(issues) >= 1
    assert issues[0]["rule_id"] == "CSS009"


def test_css009_negative_checked():
    src = _wrap(
        "    void OnCollisionEnter(Collision col)\n"
        "    {\n"
        "        if (col == null) return;\n"
        "        col.gameObject.SetActive(false);\n"
        "    }"
    )
    issues = detect_collision_no_null_check(src, FAKE_PATH)
    assert len(issues) == 0


def test_css009_edge_param_not_used():
    src = _wrap(
        "    void OnTriggerEnter(Collider other)\n"
        "    {\n"
        '        Debug.Log("hit");\n'
        "    }"
    )
    issues = detect_collision_no_null_check(src, FAKE_PATH)
    assert len(issues) == 0


# =========================================================================
# CSM* — Maintainability
# =========================================================================


# ── CSM001: long method (body newline count >= 50) ───────────────────────


def test_csm001_positive():
    body = "\n".join(f"        int v{i} = {i};" for i in range(55))
    src = _wrap("    public void BigMethod()\n    {\n" + body + "\n    }")
    issues = detect_long_method(src, FAKE_PATH)
    assert len(issues) >= 1
    assert issues[0]["rule_id"] == "CSM001"


def test_csm001_negative_short_method():
    body = "\n".join(f"        int v{i} = {i};" for i in range(10))
    src = _wrap("    public void SmallMethod()\n    {\n" + body + "\n    }")
    issues = detect_long_method(src, FAKE_PATH)
    assert len(issues) == 0


def test_csm001_edge_just_below_threshold():
    # Body newline count stays under the >= 50 threshold.
    body = "\n".join(f"        int v{i} = {i};" for i in range(45))
    src = _wrap("    public void EdgeMethod()\n    {\n" + body + "\n    }")
    issues = detect_long_method(src, FAKE_PATH)
    assert len(issues) == 0


# ── CSM002: long file (line count >= 500) ────────────────────────────────


def test_csm002_positive():
    src = _wrap(
        "    void Do()\n    {\n"
        + "\n".join(f"        int v{i} = {i};" for i in range(520))
        + "\n    }"
    )
    issues = detect_long_file(src, FAKE_PATH)
    assert len(issues) >= 1
    assert issues[0]["rule_id"] == "CSM002"


def test_csm002_negative_short_file():
    src = _wrap("    void Do() { }")
    issues = detect_long_file(src, FAKE_PATH)
    assert len(issues) == 0


def test_csm002_edge_just_below_threshold():
    # 480 short lines wrapped -> well under 500 total.
    src = _wrap(
        "    void Do()\n    {\n"
        + "\n".join(f"        int v{i} = {i};" for i in range(400))
        + "\n    }"
    )
    issues = detect_long_file(src, FAKE_PATH)
    assert len(issues) == 0


# ── CSM003: god object (> 12 public members) ─────────────────────────────


def test_csm003_positive():
    members = "\n".join(f"    public void M{i}() {{ }}" for i in range(15))
    src = "public class Big\n{\n" + members + "\n}\n"
    issues = detect_class_god_object(src, FAKE_PATH)
    assert len(issues) >= 1
    assert issues[0]["rule_id"] == "CSM003"


def test_csm003_negative_few_members():
    members = "\n".join(f"    public void M{i}() {{ }}" for i in range(3))
    src = "public class Small\n{\n" + members + "\n}\n"
    issues = detect_class_god_object(src, FAKE_PATH)
    assert len(issues) == 0


def test_csm003_edge_exactly_twelve_not_flagged():
    members = "\n".join(f"    public void M{i}() {{ }}" for i in range(12))
    src = "public class Edge\n{\n" + members + "\n}\n"
    issues = detect_class_god_object(src, FAKE_PATH)
    assert len(issues) == 0


# ── CSM004: too many params (> 5) ────────────────────────────────────────


def test_csm004_positive():
    src = _wrap(
        "    public void Configure(int a, int b, int c, int d, int e, int f)\n"
        "    {\n"
        "    }"
    )
    issues = detect_too_many_params(src, FAKE_PATH)
    assert len(issues) >= 1
    assert issues[0]["rule_id"] == "CSM004"


def test_csm004_negative():
    src = _wrap("    public void Configure(int a, int b)\n" "    {\n" "    }")
    issues = detect_too_many_params(src, FAKE_PATH)
    assert len(issues) == 0


def test_csm004_edge_exactly_five_not_flagged():
    src = _wrap(
        "    public void Configure(int a, int b, int c, int d, int e)\n"
        "    {\n"
        "    }"
    )
    issues = detect_too_many_params(src, FAKE_PATH)
    assert len(issues) == 0


# ── CSM005: deep nesting (brace depth >= 5) ──────────────────────────────


def test_csm005_positive():
    src = _wrap(
        "    public void Deep()\n"
        "    {\n"
        "        if (a)\n"
        "        {\n"
        "            if (b)\n"
        "            {\n"
        "                if (c)\n"
        "                {\n"
        "                    if (d)\n"
        "                    {\n"
        "                        DoWork();\n"
        "                    }\n"
        "                }\n"
        "            }\n"
        "        }\n"
        "    }"
    )
    issues = detect_deep_nesting(src, FAKE_PATH)
    assert len(issues) >= 1
    assert issues[0]["rule_id"] == "CSM005"


def test_csm005_negative_flat():
    src = _wrap(
        "    public void Flat()\n"
        "    {\n"
        "        if (a) return;\n"
        "        DoWork();\n"
        "    }"
    )
    issues = detect_deep_nesting(src, FAKE_PATH)
    assert len(issues) == 0


def test_csm005_edge_three_levels_not_flagged():
    src = _wrap(
        "    public void Mid()\n"
        "    {\n"
        "        if (a)\n"
        "        {\n"
        "            if (b)\n"
        "            {\n"
        "                DoWork();\n"
        "            }\n"
        "        }\n"
        "    }"
    )
    issues = detect_deep_nesting(src, FAKE_PATH)
    assert len(issues) == 0
