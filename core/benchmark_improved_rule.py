#!/usr/bin/env python3
"""
Compare: Original rule (fuzzy) vs Improved rule (specific).

Shows how better rule definition eliminates false positives.
"""

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "modules"))

from agent.custom_rule_checker import CustomRule, check_custom_rules
from agent.llm_backend import load_model

# Test files (same as before)
FILES = [
    (
        "Assets/Scripts/Auth/LoginManager.cs",
        """
using UnityEngine;
public class LoginManager : MonoBehaviour {
    public void SaveCredentials(string username, string password) {
        PlayerPrefs.SetString("username", username);
        PlayerPrefs.SetString("password", password);  // VIOLATION
        PlayerPrefs.Save();
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
        File.WriteAllText(cachePath, token);  // VIOLATION
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
        // UI code - NO credentials here
    }
}
""",
    ),
]


# ❌ ORIGINAL RULE (fuzzy, causes false positives)
RULE_FUZZY = CustomRule(
    name="Player credentials and tokens must not be stored in plain text",
    description=(
        "Credentials (passwords, API keys, auth tokens) must never be stored "
        "as plain-text string literals. Use encrypted storage or config assets."
    ),
)

# ✅ IMPROVED RULE (specific, avoids false positives)
RULE_SPECIFIC = CustomRule(
    name="Passwords, API keys, and auth tokens must not be hardcoded",
    description=(
        "Credentials are: passwords, auth tokens (authToken, accessToken, jwt), "
        "API keys (apiKey, api_key), connection strings (dbPassword, dbConnString), "
        "OAuth secrets (clientSecret). These must NEVER be hardcoded as string literals "
        "or stored in plain text. Use ScriptableObject config assets or encrypted storage only. "
        "DO NOT report: public URLs, scene names, UI button names, or generic variable names. "
        "Only flag if the variable name or context clearly indicates a credential."
    ),
    example_violation='string authToken = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...";',
)


def compare_rules():
    print("\n" + "=" * 80)
    print("RULE COMPARISON: Fuzzy vs Specific")
    print("=" * 80)

    if os.getenv("SHINTTOOLS_AGENT_ENABLED") != "1":
        print("\nERROR: Set SHINTTOOLS_AGENT_ENABLED=1")
        return

    print("\nLoading model...")
    try:
        load_model()
    except RuntimeError as e:
        print(f"ERROR: {e}\n")
        return

    print("\n" + "-" * 80)
    print("TEST 1: Original (Fuzzy) Rule")
    print("-" * 80)

    print("\nRule definition:")
    print(f"  Name: {RULE_FUZZY.name}")
    print(f"  Description length: {len(RULE_FUZZY.description)} chars")
    print(f"  Specificity: LOW (generic keywords only)\n")

    t0 = time.perf_counter()
    violations_fuzzy = check_custom_rules([RULE_FUZZY], FILES)
    t_fuzzy = time.perf_counter() - t0

    print(f"Results ({t_fuzzy:.2f}s):\n")
    for i, v in enumerate(violations_fuzzy, 1):
        is_cred = "password" in v.file_path.lower() or "token" in v.file_path.lower()
        status = "[OK]" if is_cred else "[WRONG]"
        print(f"  {status} {v.file_path}:{v.line}")
        print(f"       {v.finding[:70]}...\n")

    fp_count_fuzzy = sum(
        1
        for v in violations_fuzzy
        if "menu" in v.file_path.lower() or "ui" in v.file_path.lower()
    )

    print("\n" + "-" * 80)
    print("TEST 2: Improved (Specific) Rule")
    print("-" * 80)

    print("\nRule definition:")
    print(f"  Name: {RULE_SPECIFIC.name}")
    print(f"  Description length: {len(RULE_SPECIFIC.description)} chars")
    print(f"  Specificity: HIGH (concrete patterns + negative examples)\n")

    t0 = time.perf_counter()
    violations_specific = check_custom_rules([RULE_SPECIFIC], FILES)
    t_specific = time.perf_counter() - t0

    print(f"Results ({t_specific:.2f}s):\n")
    for i, v in enumerate(violations_specific, 1):
        is_cred = "password" in v.file_path.lower() or "token" in v.file_path.lower()
        status = "[OK]" if is_cred else "[WRONG]"
        print(f"  {status} {v.file_path}:{v.line}")
        print(f"       {v.finding[:70]}...\n")

    fp_count_specific = sum(
        1
        for v in violations_specific
        if "menu" in v.file_path.lower() or "ui" in v.file_path.lower()
    )

    # Summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)

    print(f"\nFuzzy Rule:")
    print(f"  Total violations: {len(violations_fuzzy)}")
    print(f"  False positives (UI/Menu): {fp_count_fuzzy}")
    print(
        f"  Accuracy: {(len(violations_fuzzy) - fp_count_fuzzy) / max(1, len(violations_fuzzy)) * 100:.0f}%"
    )
    print(f"  Time: {t_fuzzy:.2f}s")

    print(f"\nSpecific Rule:")
    print(f"  Total violations: {len(violations_specific)}")
    print(f"  False positives (UI/Menu): {fp_count_specific}")
    print(
        f"  Accuracy: {(len(violations_specific) - fp_count_specific) / max(1, len(violations_specific)) * 100:.0f}%"
    )
    print(f"  Time: {t_specific:.2f}s")

    print(f"\nImprovement:")
    improvement = fp_count_fuzzy - fp_count_specific
    print(f"  False positives reduced by: {improvement}")
    print(
        f"  Accuracy gain: {(improvement / max(1, fp_count_fuzzy)) * 100:.0f}%"
        if fp_count_fuzzy > 0
        else "  N/A"
    )

    print("\n" + "=" * 80 + "\n")


if __name__ == "__main__":
    compare_rules()
