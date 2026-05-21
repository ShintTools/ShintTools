# core/scripts/_smoke_unity_20.py
#
# Smoke test: Qwen on 20 Unity rules — C# Security, Performance,
# Best Practices, Maintainability, Unity-Specific, and Visual Scripting.
# Run from core/:  python -m scripts._smoke_unity_20

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules.agent.explainer import explain_issue  # noqa: E402
from modules.agent.llm_backend import load_model  # noqa: E402

# ── Test cases ──────────────────────────────────────────────────────────────

CASES: List[Dict[str, Any]] = [
    # ── C# Security ────────────────────────────────────────────────────────
    {
        "label": "CSS001 — SQL command by string concatenation",
        "issue": {
            "rule_id": "CSS001",
            "rule_name": "SQL command built by string concatenation",
            "rule_explanation": (
                "SQL command built by string concatenation — injection risk. "
                "Any user-controlled value concatenated directly into a SQL "
                "string allows an attacker to modify the query. Use parameterised "
                "queries or an ORM to pass values safely."
            ),
            "severity": "error",
            "category": "Security",
            "file_path": "Assets/Scripts/Database/PlayerDataService.cs",
            "line": 42,
            "context_before": (
                "    public void LoadPlayer(string username)\n"
                "    {\n"
                '        string sql = "SELECT * FROM players WHERE name = \'" + username + "\'";\n'  # noqa: E501
                "        ExecuteQuery(sql);\n"
                "    }"
            ),
            "message": "SQL query built by string concatenation — injection risk",
            "is_auto_fixable": False,
        },
    },
    {
        "label": "CSS002 — Hard-coded API key in source",
        "issue": {
            "rule_id": "CSS002",
            "rule_name": "Hard-coded secret in source",
            "rule_explanation": (
                "Literal credentials in source (password = '...', api_key = '...'). "
                "Hard-coded secrets committed to version control can be leaked "
                "via git history even after the line is deleted. Move them to "
                "environment variables or a secrets manager and read them at runtime."
            ),
            "severity": "error",
            "category": "Security",
            "file_path": "Assets/Scripts/Analytics/AnalyticsManager.cs",
            "line": 8,
            "context_before": (
                "public class AnalyticsManager : MonoBehaviour\n"
                "{\n"
                '    private const string _apiKey = "sk-live-7f3a91bc2d";\n'
                '    private const string _secret = "supersecret123";\n'
            ),
            "message": "Hard-coded secret literal found — move to environment variable",
            "is_auto_fixable": False,
        },
    },
    # ── C# Performance ─────────────────────────────────────────────────────
    {
        "label": "CSP001 — LINQ in Update",
        "issue": {
            "rule_id": "CSP001",
            "rule_name": "LINQ operator in Update",
            "rule_explanation": (
                "LINQ chain inside Update — allocates enumerator+lambda each frame. "
                "Every LINQ call (Where, Select, FirstOrDefault, etc.) creates at least "  # noqa: E501
                "one managed heap allocation per frame, keeping the GC busy and "
                "causing periodic frame spikes. Use a plain for-loop or cache results "
                "outside Update."
            ),
            "severity": "warning",
            "category": "Performance",
            "file_path": "Assets/Scripts/Game/EnemyManager.cs",
            "line": 34,
            "context_before": (
                "    void Update()\n"
                "    {\n"
                "        var active = _enemies.Where(e => e.IsAlive).ToList();\n"
                "        foreach (var e in active) e.Tick(Time.deltaTime);\n"
                "    }"
            ),
            "message": "LINQ chain inside Update — allocates each frame",
            "is_auto_fixable": False,
        },
    },
    {
        "label": "CSP004 — Instantiate inside Update",
        "issue": {
            "rule_id": "CSP004",
            "rule_name": "Instantiate in Update",
            "rule_explanation": (
                "Instantiate inside Update — per-frame GameObject allocation. "
                "Each Instantiate call allocates managed memory, triggers "
                "component Awake/Start, and can cause visible frame spikes "
                "when the GC collects. Use an object pool and activate/deactivate "
                "instead of creating and destroying every frame."
            ),
            "severity": "warning",
            "category": "Performance",
            "file_path": "Assets/Scripts/Gameplay/BulletSpawner.cs",
            "line": 21,
            "context_before": (
                "    void Update()\n"
                "    {\n"
                "        if (Input.GetKey(KeyCode.Space))\n"
                "            Instantiate(bulletPrefab, firePoint.position, Quaternion.identity);\n"  # noqa: E501
                "    }"
            ),
            "message": "Instantiate called inside Update — per-frame allocation",
            "is_auto_fixable": False,
        },
    },
    {
        "label": "CSP006 — new WaitForSeconds per yield",
        "issue": {
            "rule_id": "CSP006",
            "rule_name": "new WaitForSeconds per yield",
            "rule_explanation": (
                "`yield return new WaitForSeconds(x)` — allocates each yield. "
                "Creating a new WaitForSeconds object on every coroutine iteration "
                "generates GC garbage for every wait. Cache the instance in a "
                "private field and reuse it to avoid the allocation."
            ),
            "severity": "warning",
            "category": "Performance",
            "file_path": "Assets/Scripts/UI/FadeController.cs",
            "line": 17,
            "context_before": (
                "    IEnumerator FadeLoop()\n"
                "    {\n"
                "        while (true)\n"
                "        {\n"
                "            yield return new WaitForSeconds(0.1f);\n"
                "            _alpha -= 0.05f;\n"
                "        }\n"
                "    }"
            ),
            "message": "`new WaitForSeconds(...)` per yield — allocates each iteration",
            "is_auto_fixable": False,
        },
    },
    {
        "label": "CSP008 — Update body too large",
        "issue": {
            "rule_id": "CSP008",
            "rule_name": "Update method body too large",
            "rule_explanation": (
                "Update method body exceeds 50 lines — too much work per frame. "
                "A large Update method is hard to profile, hard to read, and "
                "makes it difficult to identify which logic dominates the frame "
                "budget. Extract cohesive sub-tasks into private helper methods "
                "or separate MonoBehaviours."
            ),
            "severity": "warning",
            "category": "Performance",
            "file_path": "Assets/Scripts/Player/PlayerController.cs",
            "line": 1,
            "context_before": (
                "    // Update method spans lines 1–67\n"
                "    void Update()\n"
                "    {\n"
                "        HandleInput();\n"
                "        ApplyGravity();\n"
                "        // ... 62 more lines ..."
            ),
            "message": "Update method body is 67 lines — exceeds 50-line limit",
            "is_auto_fixable": False,
        },
    },
    {
        "label": "CSP009 — Collection copied inside loop",
        "issue": {
            "rule_id": "CSP009",
            "rule_name": "Collection copied in loop",
            "rule_explanation": (
                "new List<T>(existing) or .ToList()/.ToArray() inside a loop — "
                "O(n) allocation per iteration. Every iteration copies the entire "
                "collection onto the managed heap, which multiplies GC pressure "
                "proportionally to loop count. Hoist the copy before the loop or "
                "iterate the source directly."
            ),
            "severity": "warning",
            "category": "Performance",
            "file_path": "Assets/Scripts/AI/PathFinder.cs",
            "line": 55,
            "context_before": (
                "    for (int i = 0; i < waypoints.Count; i++)\n"
                "    {\n"
                "        var copy = waypoints.ToList();\n"
                "        copy.RemoveAt(i);\n"
                "        EvaluatePath(copy);\n"
                "    }"
            ),
            "message": ".ToList() inside loop — O(n) allocation per iteration",
            "is_auto_fixable": False,
        },
    },
    # ── C# Best Practices ──────────────────────────────────────────────────
    {
        "label": "CSB001 — Empty catch block",
        "issue": {
            "rule_id": "CSB001",
            "rule_name": "Empty catch block",
            "rule_explanation": (
                "Empty catch block swallows exceptions silently. An empty catch "
                "discards the exception without any logging or recovery, hiding "
                "bugs and making failures impossible to diagnose. At minimum log "
                "the exception with Debug.LogException before re-throwing or "
                "handling it."
            ),
            "severity": "warning",
            "category": "BestPractices",
            "file_path": "Assets/Scripts/Networking/NetworkManager.cs",
            "line": 88,
            "context_before": (
                "    try\n"
                "    {\n"
                "        _client.Connect(serverAddress, port);\n"
                "    }\n"
                "    catch (Exception)\n"
                "    {\n"
                "    }"
            ),
            "message": "Empty catch block — exception swallowed silently",
            "is_auto_fixable": False,
        },
    },
    {
        "label": "CSB003 — Broad catch (Exception) without rethrow",
        "issue": {
            "rule_id": "CSB003",
            "rule_name": "Broad catch (Exception) without rethrow or log",
            "rule_explanation": (
                "`catch (Exception)` without filter — swallows specific errors. "
                "Catching the base Exception type without rethrowing or logging "
                "hides every possible exception including NullReferenceException "
                "and StackOverflowException. Catch specific exception types, or "
                "at minimum log and rethrow."
            ),
            "severity": "warning",
            "category": "BestPractices",
            "file_path": "Assets/Scripts/SaveSystem/SaveManager.cs",
            "line": 63,
            "context_before": (
                "    try\n"
                "    {\n"
                "        File.WriteAllText(savePath, json);\n"
                "    }\n"
                "    catch (Exception e)\n"
                "    {\n"
                "        _hasSaved = false;\n"
                "    }"
            ),
            "message": "`catch (Exception)` without rethrow or logging — masks bugs",
            "is_auto_fixable": False,
        },
    },
    {
        "label": "CSB005 — async void method",
        "issue": {
            "rule_id": "CSB005",
            "rule_name": "async void non-event-handler",
            "rule_explanation": (
                "`async void` method — exceptions crash the process. "
                "Exceptions thrown inside async void cannot be caught by "
                "the caller because there is no Task to observe. They propagate "
                "directly to the SynchronizationContext and crash Unity. Change "
                "the return type to async Task (or async UniTask) so the caller "
                "can await and observe errors."
            ),
            "severity": "warning",
            "category": "BestPractices",
            "file_path": "Assets/Scripts/Backend/LeaderboardService.cs",
            "line": 29,
            "context_before": (
                "    public async void SubmitScore(int score)\n"
                "    {\n"
                "        var response = await _http.PostAsync(apiUrl, score);\n"
                "        UpdateUI(response);\n"
                "    }"
            ),
            "message": (
                "async void method 'SubmitScore'"
                " — uncaught exceptions crash the process"
            ),
            "is_auto_fixable": False,
        },
    },
    # ── C# Maintainability ─────────────────────────────────────────────────
    {
        "label": "CSM001 — Method exceeds 50 lines",
        "issue": {
            "rule_id": "CSM001",
            "rule_name": "Method exceeds 50 lines",
            "rule_explanation": (
                "Method body exceeds 50 lines. Long methods are hard to read, "
                "test in isolation, and refactor safely. Each cohesive sub-task "
                "should be extracted into its own named private method so that "
                "the top-level method reads like a table of contents."
            ),
            "severity": "info",
            "category": "Maintainability",
            "file_path": "Assets/Scripts/UI/InventoryScreen.cs",
            "line": 45,
            "context_before": (
                "    public void RefreshInventory()\n"
                "    {\n"
                "        // ... method spans 78 lines ...\n"
                "        ClearSlots();\n"
                "        PopulateSlots();\n"
            ),
            "message": "Method 'RefreshInventory' is 78 lines — exceeds 50-line limit",
            "is_auto_fixable": False,
        },
    },
    {
        "label": "CSM004 — Too many method parameters",
        "issue": {
            "rule_id": "CSM004",
            "rule_name": "Method has too many parameters",
            "rule_explanation": (
                "Method with > 5 parameters — bundle into a struct/options class. "
                "Methods with many parameters are hard to call correctly, easy to "
                "mix up argument order, and difficult to extend without breaking "
                "all callers. Group related parameters into a dedicated options "
                "struct or class."
            ),
            "severity": "info",
            "category": "Maintainability",
            "file_path": "Assets/Scripts/Audio/AudioManager.cs",
            "line": 102,
            "context_before": (
                "    public void PlaySound(\n"
                "        AudioClip clip, float volume, float pitch,\n"
                "        Vector3 position, bool loop, AudioMixerGroup group)\n"
                "    {"
            ),
            "message": "Method 'PlaySound' has 6 parameters — exceeds 5-parameter limit",  # noqa: E501
            "is_auto_fixable": False,
        },
    },
    # ── Unity-Specific ─────────────────────────────────────────────────────
    {
        "label": "UN001 — GameObject.Find in Update",
        "issue": {
            "rule_id": "UN001",
            "rule_name": "GameObject.Find in Update",
            "rule_explanation": (
                "GameObject.Find inside Update — O(scene) every frame. "
                "Unity's GameObject.Find iterates every active GameObject in "
                "the scene on each call. Calling it in Update runs that scan "
                "60-120 times per second and is one of the most common causes "
                "of unexpected Update overhead. Cache the reference in Awake or "
                "Start instead."
            ),
            "severity": "warning",
            "category": "Performance",
            "file_path": "Assets/Scripts/UI/HUDManager.cs",
            "line": 18,
            "context_before": (
                "    void Update()\n"
                "    {\n"
                '        var player = GameObject.Find("Player");\n'
                "        _healthBar.value = player.GetComponent<Health>().current;\n"
                "    }"
            ),
            "message": "GameObject.Find called inside Update — full scene search every frame",  # noqa: E501
            "is_auto_fixable": False,
        },
    },
    {
        "label": "UN003 — FindObjectOfType in Update",
        "issue": {
            "rule_id": "UN003",
            "rule_name": "FindObjectOfType in Update",
            "rule_explanation": (
                "FindObjectOfType / FindAnyObjectByType inside Update. "
                "Like GameObject.Find, FindObjectOfType iterates all active "
                "MonoBehaviours in the scene on every call. Inside Update this "
                "is a repeated O(scene) scan that adds measurable overhead "
                "every frame. Cache the result in Awake and hold a reference."
            ),
            "severity": "warning",
            "category": "Performance",
            "file_path": "Assets/Scripts/Quest/QuestTracker.cs",
            "line": 31,
            "context_before": (
                "    void Update()\n"
                "    {\n"
                "        var mgr = FindObjectOfType<QuestManager>();\n"
                "        if (mgr != null) _label.text = mgr.ActiveQuestName;\n"
                "    }"
            ),
            "message": "FindObjectOfType called inside Update — scene scan every frame",
            "is_auto_fixable": False,
        },
    },
    {
        "label": "UN004 — Debug.Log inside Update",
        "issue": {
            "rule_id": "UN004",
            "rule_name": "Debug.Log in Update",
            "rule_explanation": (
                "Debug.Log inside Update — IO + string format every frame. "
                "Each Debug.Log call formats a string, writes to the Unity "
                "console log file, and triggers a stack-trace capture in "
                "development builds. Called every frame this produces "
                "measurable GC pressure and disk I/O. Gate it behind a "
                "conditional or remove it before shipping."
            ),
            "severity": "warning",
            "category": "Performance",
            "file_path": "Assets/Scripts/Player/MovementController.cs",
            "line": 27,
            "context_before": (
                "    void Update()\n"
                "    {\n"
                "        _velocity = CalculateVelocity();\n"
                '        Debug.Log($"Velocity: {_velocity}");\n'
                "        ApplyVelocity(_velocity);\n"
                "    }"
            ),
            "message": "Debug.Log called inside Update — IO every frame",
            "is_auto_fixable": False,
        },
    },
    {
        "label": "UN008 — Camera.main inside Update",
        "issue": {
            "rule_id": "UN008",
            "rule_name": "Camera.main in Update",
            "rule_explanation": (
                "Camera.main inside Update. Camera.main is "
                "GameObject.FindGameObjectWithTag('MainCamera') under the hood — "
                "it does a full scene tag-search on every access. Reading it "
                "inside Update repeats that search every frame. Cache the camera "
                "reference in Start and reuse it."
            ),
            "severity": "warning",
            "category": "Performance",
            "file_path": "Assets/Scripts/Game/CameraFollow.cs",
            "line": 14,
            "context_before": (
                "    void Update()\n"
                "    {\n"
                "        Vector3 pos = Camera.main.transform.position;\n"
                "        transform.position = Vector3.Lerp(transform.position, pos, 0.1f);\n"  # noqa: E501
                "    }"
            ),
            "message": "Camera.main accessed inside Update — implicit scene search every frame",  # noqa: E501
            "is_auto_fixable": False,
        },
    },
    {
        "label": "UN011 — transform.position in loop",
        "issue": {
            "rule_id": "UN011",
            "rule_name": "Transform modified in a loop",
            "rule_explanation": (
                "transform.position/rotation written inside a loop — each write "
                "notifies the physics engine. Every assignment to transform.position "
                "or transform.rotation sends a dirty notification to PhysX, which "
                "recalculates contact data. In a tight loop this can produce "
                "hundreds of physics updates per frame. Accumulate the final value "
                "and write it once after the loop."
            ),
            "severity": "warning",
            "category": "Performance",
            "file_path": "Assets/Scripts/Formation/FormationManager.cs",
            "line": 72,
            "context_before": (
                "    foreach (var unit in _units)\n"
                "    {\n"
                "        unit.transform.position = ComputeSlot(unit.index);\n"
                "        unit.transform.rotation = _facing;\n"
                "    }"
            ),
            "message": "transform.position written inside loop — physics notified per iteration",  # noqa: E501
            "is_auto_fixable": False,
        },
    },
    # ── Unity Visual Scripting ─────────────────────────────────────────────
    {
        "label": "VSP003 — GetComponent in Update graph",
        "issue": {
            "rule_id": "VSP003",
            "rule_name": "GetComponent node inside an Update graph",
            "rule_explanation": (
                "GetComponent call inside an Update graph — O(n) component "
                "lookup every frame. The GetComponent node traverses the "
                "GameObject's component list on every Update tick. Cache the "
                "component reference in an OnStart node, store it in a graph "
                "variable, and read the variable in Update instead."
            ),
            "severity": "warning",
            "category": "Performance",
            "asset_path": "Assets/Game/Enemies/SlimeController.asset",
            "message": "GetComponent node inside Update graph — component lookup every frame",  # noqa: E501
            "is_auto_fixable": False,
        },
    },
    {
        "label": "VSP004 — FindGameObject in Update graph",
        "issue": {
            "rule_id": "VSP004",
            "rule_name": "Find node inside an Update graph",
            "rule_explanation": (
                "FindObject / FindObjectOfType inside an Update graph — full "
                "scene scan every frame. The Find node iterates all active "
                "GameObjects in the scene on every Update tick. Cache the "
                "reference once in an OnStart node or assign it via an exposed "
                "Object field on the Script Machine."
            ),
            "severity": "error",
            "category": "Performance",
            "asset_path": "Assets/Game/UI/ScoreboardGraph.asset",
            "message": "FindGameObject node in Update graph — scene scan every frame",
            "is_auto_fixable": False,
        },
    },
    {
        "label": "VSB005 — GetComponent without null check",
        "issue": {
            "rule_id": "VSB005",
            "rule_name": "GetComponent node without null-check",
            "rule_explanation": (
                "GetComponent node present but no NullCheck node found — "
                "if the component is missing the graph will silently propagate "
                "a null and crash downstream. Add a NullCheck node after "
                "GetComponent and wire the null branch to a Log error node or "
                "an early-exit branch."
            ),
            "severity": "warning",
            "category": "BestPractices",
            "asset_path": "Assets/Game/Player/HealthGraph.asset",
            "message": (
                "GetComponent node present but no NullCheck found"
                " — null propagates silently"
            ),
            "is_auto_fixable": False,
        },
    },
]

# ── Runner ──────────────────────────────────────────────────────────────────


def run() -> None:
    print("Loading model...")
    t_load_start = time.perf_counter()
    load_model()
    t_load_end = time.perf_counter()
    print(f"Model ready. (load: {t_load_end - t_load_start:.1f}s)\n")

    passed = 0
    failed = 0
    times: list[float] = []

    for case in CASES:
        label = case["label"]
        issue = case["issue"]
        print("=" * 70)
        print(f"RULE: {label}")
        asset = issue.get("asset_path", issue.get("file_path", ""))
        print(f"asset: {asset}")
        print(f"auto_fixable: {issue['is_auto_fixable']}")
        print("-" * 70)

        try:
            t0 = time.perf_counter()
            explanation = explain_issue(issue)
            elapsed = time.perf_counter() - t0
            times.append(elapsed)
            if not explanation:
                print(f"[FAIL] Empty explanation returned ({elapsed:.1f}s)")
                failed += 1
                continue

            print(explanation)
            print(f"  time: {elapsed:.1f}s")

            expected_closing = (
                "ShintTools' Auto-Fix can apply it for you."
                if issue["is_auto_fixable"]
                else "You must fix this manually."
            )
            has_closing = expected_closing in explanation

            print()
            if has_closing:
                print("  [OK] closing line correct")
                passed += 1
            else:
                print(f"  [WARN] closing line wrong — expected: '{expected_closing}'")
                failed += 1

        except Exception as e:
            elapsed = time.perf_counter() - t0
            times.append(elapsed)
            print(f"[ERROR] {type(e).__name__}: {e} ({elapsed:.1f}s)")
            failed += 1

        print()

    print("=" * 70)
    print(f"RESULTS: {passed}/{passed + failed} passed")
    if failed:
        print(f"  {failed} case(s) need review")
    if times:
        total = sum(times)
        avg = total / len(times)
        first3 = sum(times[:3]) / 3
        last3 = sum(times[-3:]) / 3
        print(f"\nTIMING ({len(times)} inferences):")
        print(f"  Total inference:  {total:.1f}s")
        print(f"  Average per case: {avg:.1f}s")
        print(f"  First 3 avg:      {first3:.1f}s")
        print(f"  Last  3 avg:      {last3:.1f}s")
        print("  Per-case: " + ", ".join(f"{t:.1f}" for t in times))


if __name__ == "__main__":
    run()
