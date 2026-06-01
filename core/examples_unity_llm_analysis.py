#!/usr/bin/env python3
"""
Three realistic examples of LLM-based asset analysis in Unity.

Each example shows:
  1. A user-defined rule (natural language)
  2. A batch of Unity asset files
  3. The prompt sent to the LLM
  4. The expected JSON response
  5. The parsed violations

Run with: python examples_unity_llm_analysis.py
"""

import json
from dataclasses import dataclass


@dataclass
class Example:
    name: str
    rule_problem: str
    rule_solution: str
    files: dict[str, str]  # path → content
    expected_violations: list[dict]  # what the LLM should find


# ──────────────────────────────────────────────────────────────────────────


EXAMPLE_1 = Example(
    name="Hardcoded Server URLs in Network Code",
    rule_problem="NetworkManager must not hardcode production server URLs",
    rule_solution=(
        "Move hardcoded URLs to a separate ScriptableObject config asset "
        "or environment variable. Instantiate the config at runtime."
    ),
    files={
        "Assets/Scripts/Network/GameServer.cs": """
using UnityEngine;
using System.Collections.Generic;

public class GameServer : MonoBehaviour {
    private string serverUrl = "https://prod-api.company.com/v1/game";
    private string backupUrl = "https://backup.company.com";

    void Start() {
        ConnectToServer(serverUrl);
    }

    void ConnectToServer(string url) {
        // Connection logic
    }
}
""",
        "Assets/Scripts/Network/PlayerSync.cs": """
using UnityEngine;

public class PlayerSync : MonoBehaviour {
    void Update() {
        // Sync player state to server
        SendPositionUpdate(transform.position);
    }

    void SendPositionUpdate(Vector3 pos) {
        // Use NetworkManager's URL (configuration-based)
    }
}
""",
        "Assets/Scripts/Config/ServerConfig.cs": """
using UnityEngine;

[CreateAssetMenu(fileName = "ServerConfig", menuName = "Game/Server Config")]
public class ServerConfig : ScriptableObject {
    public string productionUrl = "https://prod-api.company.com/v1/game";
    public string stagingUrl = "https://staging-api.company.com/v1/game";
}
""",
    },
    expected_violations=[
        {
            "file": "Assets/Scripts/Network/GameServer.cs",
            "line": 4,
            "finding": "Production server URL hardcoded as string literal (https://prod-api.company.com/v1/game).",
            "fix": "Move URL to a ScriptableObject config asset and load it via Resources.Load<ServerConfig>() at runtime.",
        }
    ],
)


EXAMPLE_2 = Example(
    name="Unencrypted Sensitive Data Storage",
    rule_problem="Player credentials and tokens must not be stored in plain text",
    rule_solution=(
        "Use encrypted PlayerPrefs or a secure storage backend. "
        "Never serialize credentials directly to disk."
    ),
    files={
        "Assets/Scripts/Auth/LoginManager.cs": """
using UnityEngine;

public class LoginManager : MonoBehaviour {
    public void SaveCredentials(string username, string password) {
        PlayerPrefs.SetString("username", username);
        PlayerPrefs.SetString("password", password);  // VIOLATION: plain text
        PlayerPrefs.Save();
    }

    public void LoadCredentials(out string username, out string password) {
        username = PlayerPrefs.GetString("username", "");
        password = PlayerPrefs.GetString("password", "");
    }
}
""",
        "Assets/Scripts/Auth/TokenManager.cs": """
using UnityEngine;
using System.IO;

public class TokenManager : MonoBehaviour {
    void CacheAuthToken(string token) {
        string cachePath = Path.Combine(Application.persistentDataPath, "auth_token.txt");
        File.WriteAllText(cachePath, token);  // VIOLATION: unencrypted file write
    }

    string LoadCachedToken() {
        string cachePath = Path.Combine(Application.persistentDataPath, "auth_token.txt");
        if (File.Exists(cachePath)) {
            return File.ReadAllText(cachePath);
        }
        return null;
    }
}
""",
        "Assets/Scripts/Auth/SecureAuth.cs": """
using UnityEngine;
using System.Security.Cryptography;
using System.Text;

public class SecureAuth : MonoBehaviour {
    public void SaveEncryptedCredentials(string username, string password) {
        // Proper implementation: use DPAPI or similar
        byte[] plaintext = Encoding.UTF8.GetBytes(password);
        byte[] encrypted = ProtectedData.Protect(plaintext, null, DataProtectionScope.CurrentUser);
        PlayerPrefs.SetString("enc_password", System.Convert.ToBase64String(encrypted));
        PlayerPrefs.Save();
    }
}
""",
    },
    expected_violations=[
        {
            "file": "Assets/Scripts/Auth/LoginManager.cs",
            "line": 4,
            "finding": "Password stored in plain text via PlayerPrefs.",
            "fix": "Use encrypted PlayerPrefs or ProtectedData.Protect() before storing.",
        },
        {
            "file": "Assets/Scripts/Auth/TokenManager.cs",
            "line": 4,
            "finding": "Authentication token written to unencrypted file.",
            "fix": "Encrypt the token using ProtectedData.Protect() before writing to disk.",
        },
    ],
)


EXAMPLE_3 = Example(
    name="Scene References in Code (Hard-coded Scene Names)",
    rule_problem="Scene names must not be hard-coded as magic strings",
    rule_solution=(
        "Create a ScriptableObject or enum defining all scene names. "
        "Reference them via constants, never via quoted strings."
    ),
    files={
        "Assets/Scripts/SceneManagement/LevelLoader.cs": """
using UnityEngine;
using UnityEngine.SceneManagement;

public class LevelLoader : MonoBehaviour {
    public void LoadMainMenu() {
        SceneManager.LoadScene("MainMenu");  // VIOLATION: hard-coded scene name
    }

    public void LoadGameplayLevel(int levelNumber) {
        string sceneName = $"Level_{levelNumber}";
        SceneManager.LoadScene(sceneName);
    }

    public void LoadCredits() {
        SceneManager.LoadScene("CreditsScene");  // VIOLATION
    }
}
""",
        "Assets/Scripts/SceneManagement/PauseManager.cs": """
using UnityEngine;
using UnityEngine.SceneManagement;

public class PauseManager : MonoBehaviour {
    private bool isPaused = false;

    void Update() {
        if (Input.GetKeyDown(KeyCode.Escape)) {
            if (isPaused) {
                ResumeGame();
            } else {
                PauseGame();
            }
        }
    }

    void ResumeGame() {
        Time.timeScale = 1f;
        isPaused = false;
    }

    void PauseGame() {
        Time.timeScale = 0f;
        isPaused = true;
    }
}
""",
        "Assets/Scripts/SceneManagement/SceneNames.cs": """
using UnityEngine;

public static class SceneNames {
    public const string MAIN_MENU = "MainMenu";
    public const string GAMEPLAY = "Gameplay";
    public const string CREDITS = "CreditsScene";
    public const string SETTINGS = "Settings";
}
""",
        "Assets/Scripts/UI/MenuController.cs": """
using UnityEngine;
using UnityEngine.SceneManagement;

public class MenuController : MonoBehaviour {
    public void OnPlayClicked() {
        // Proper implementation: use the constant
        SceneManager.LoadScene(SceneNames.GAMEPLAY);
    }

    public void OnCreditsClicked() {
        SceneManager.LoadScene(SceneNames.CREDITS);
    }

    public void OnSettingsClicked() {
        SceneManager.LoadScene(SceneNames.SETTINGS);
    }
}
""",
    },
    expected_violations=[
        {
            "file": "Assets/Scripts/SceneManagement/LevelLoader.cs",
            "line": 6,
            "finding": "Scene name 'MainMenu' hard-coded as string literal.",
            "fix": "Use SceneNames.MAIN_MENU constant instead of magic string.",
        },
        {
            "file": "Assets/Scripts/SceneManagement/LevelLoader.cs",
            "line": 12,
            "finding": "Scene name 'CreditsScene' hard-coded as string literal.",
            "fix": "Use SceneNames.CREDITS constant instead of magic string.",
        },
    ],
)


# ──────────────────────────────────────────────────────────────────────────


def format_prompt(rule_problem: str, rule_solution: str, files: dict[str, str]) -> str:
    """Format the checker prompt as it would be sent to the LLM."""
    files_section = "\n\n".join(
        f"--- file: {path} ---\n{content.strip()}" for path, content in files.items()
    )
    return f"""RULE
name: {rule_problem}
description: {rule_solution}

FILES
{files_section}

OUTPUT
"""


def print_example(example: Example):
    """Print a formatted example with prompt, expected response, and violations."""
    print(f"\n{'=' * 80}")
    print(f"EXAMPLE: {example.name}")
    print(f"{'=' * 80}\n")

    # Rule
    print("[RULE]")
    print(f"  Problem:  {example.rule_problem}")
    print(f"  Solution: {example.rule_solution}\n")

    # Files
    print("[FILES]")
    for path in example.files.keys():
        print(f"  - {path}")
    print()

    # Prompt
    print("[PROMPT SENT TO LLM]")
    print("-" * 80)
    prompt = format_prompt(example.rule_problem, example.rule_solution, example.files)
    print(prompt)
    print("-" * 80)
    print()

    # Expected response
    print("[LLM RESPONSE (JSON)]")
    print("-" * 80)
    response = json.dumps(example.expected_violations, indent=2)
    print(response)
    print("-" * 80)
    print()

    # Parsed violations
    print("[PARSED VIOLATIONS]")
    if example.expected_violations:
        for v in example.expected_violations:
            print(f"  * {v['file']}:{v['line']}")
            print(f"    Finding: {v['finding']}")
            print(f"    Fix: {v['fix']}\n")
    else:
        print("  (None -- code is clean!)\n")


# ──────────────────────────────────────────────────────────────────────────


if __name__ == "__main__":
    print("\n" + "UNITY ASSET TOOL - LLM ANALYSIS EXAMPLES".center(80, "="))
    print("Three realistic scenarios of natural-language rule checking\n")

    for example in [EXAMPLE_1, EXAMPLE_2, EXAMPLE_3]:
        print_example(example)

    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"[OK] Example 1: {len(EXAMPLE_1.expected_violations)} violation(s) detected")
    print(f"[OK] Example 2: {len(EXAMPLE_2.expected_violations)} violation(s) detected")
    print(f"[OK] Example 3: {len(EXAMPLE_3.expected_violations)} violation(s) detected")
    print(
        f"\nTotal: {sum(len(e.expected_violations) for e in [EXAMPLE_1, EXAMPLE_2, EXAMPLE_3])} violations across all examples"
    )
    print(
        "\nThese violations would be returned by /assets/unity/scan as Layer 3 findings"
    )
    print(
        "(genericRule index, path, fix) when SHINTTOOLS_AGENT_ENABLED=1 for indie+ tiers.\n"
    )
