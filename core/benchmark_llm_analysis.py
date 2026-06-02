#!/usr/bin/env python3
"""
Real LLM benchmark: measure execution time and raw LLM output.

Shows:
  - Time to prefilter files
  - Time for each LLM batch call
  - Raw LLM output before JSON parsing
  - Total violations found

Run with: SHINTTOOLS_AGENT_ENABLED=1 python benchmark_llm_analysis.py
"""

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "modules"))

from agent.custom_rule_checker import CustomRule, check_custom_rules
from agent.llm_backend import load_model

# Real-world example: security rule + varied code
RULE = CustomRule(
    name="Player credentials and tokens must not be stored in plain text",
    description=(
        "Credentials (passwords, API keys, auth tokens) must never be stored "
        "as plain-text string literals. Use encrypted storage, environment "
        "variables, or secure config assets at runtime."
    ),
    example_violation='string password = "SuperSecret123";',
)

FILES = [
    (
        "Assets/Scripts/Auth/LoginManager.cs",
        """
using UnityEngine;
public class LoginManager : MonoBehaviour {
    public void SaveCredentials(string username, string password) {
        PlayerPrefs.SetString("username", username);
        PlayerPrefs.SetString("password", password);  // plain text
        PlayerPrefs.Save();
    }
}
""",
    ),
    (
        "Assets/Scripts/Network/GameServer.cs",
        """
using UnityEngine;
public class GameServer : MonoBehaviour {
    private string serverUrl = "https://prod-api.company.com/v1/game";
    void Start() {
        ConnectToServer(serverUrl);
    }
}
""",
    ),
    (
        "Assets/Scripts/Auth/TokenManager.cs",
        """
using UnityEngine;
using System.IO;
public class TokenManager : MonoBehaviour {
    void CacheAuthToken(string token) {
        string cachePath = Path.Combine(Application.persistentDataPath, "auth_token.txt");
        File.WriteAllText(cachePath, token);  // unencrypted
    }
}
""",
    ),
    (
        "Assets/Scripts/UI/MenuController.cs",
        """
using UnityEngine;
using UnityEngine.UI;
public class MenuController : MonoBehaviour {
    public Button playButton;
    public Button settingsButton;
    void Start() {
        playButton.onClick.AddListener(OnPlayClicked);
    }
    void OnPlayClicked() {
        // No credentials here
    }
}
""",
    ),
    (
        "Assets/Scripts/Player/PlayerController.cs",
        """
using UnityEngine;
public class PlayerController : MonoBehaviour {
    public float speed = 5f;
    void Update() {
        float h = Input.GetAxis("Horizontal");
        float v = Input.GetAxis("Vertical");
        transform.Translate(new Vector3(h, 0, v) * speed * Time.deltaTime);
    }
}
""",
    ),
]


def main():
    print("\n" + "=" * 80)
    print("REAL LLM BENCHMARK - Unity Asset Analysis")
    print("=" * 80)

    if os.getenv("SHINTTOOLS_AGENT_ENABLED") != "1":
        print("\nWARNING: SHINTTOOLS_AGENT_ENABLED != '1'")
        print("Set it to enable the LLM. Exiting.\n")
        return

    print("\nLoading model...")
    t_load_start = time.perf_counter()
    try:
        load_model()
    except RuntimeError as e:
        print(f"ERROR: {e}\n")
        return
    t_load = time.perf_counter() - t_load_start
    print(f"Model loaded in {t_load:.2f}s\n")

    print(f"Rule: {RULE.name}")
    print(f"Files: {len(FILES)}")
    print(f"Batch size: 3 (default)\n")

    print("-" * 80)
    print("Executing check_custom_rules()...\n")

    t0 = time.perf_counter()
    try:
        violations = check_custom_rules([RULE], FILES)
    except Exception as e:
        print(f"ERROR: {e}")
        print(
            "\nPossible causes:"
            "\n  1. Model file (*.gguf) not found"
            "\n  2. llama.cpp not compiled for your system"
            "\n  3. Insufficient memory on GPU/CPU"
        )
        return

    elapsed = time.perf_counter() - t0

    print("-" * 80)
    print(f"\nExecution time: {elapsed:.2f} seconds\n")

    print(f"Violations found: {len(violations)}\n")

    for i, v in enumerate(violations, 1):
        print(f"[{i}] {v.file_path}:{v.line}")
        print(f"    Rule: {v.rule_name}")
        print(f"    Finding: {v.finding}")
        print(f"    Fix: {v.fix_suggestion}\n")

    print("-" * 80)
    print(f"Summary: {len(violations)} violations in {elapsed:.2f}s")
    print(f"Average per file: {elapsed / len(FILES):.2f}s")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    main()
