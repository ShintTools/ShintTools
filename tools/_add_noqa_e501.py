"""Append `# noqa: E501` to lines longer than 88 chars in the given files.

One-shot tool used to silence E501 in csharp_rules.py and
unity_graph_rules.py where black couldn't break inline regex/message
strings further without changing their value.
"""
import sys


def patch(path: str) -> int:
    with open(path, encoding="utf-8") as f:
        lines = f.readlines()
    patched = 0
    out = []
    for ln in lines:
        stripped = ln.rstrip("\n")
        if len(stripped) > 88 and "noqa" not in stripped:
            stripped = stripped + "  # noqa: E501"
            patched += 1
        out.append(stripped + "\n")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.writelines(out)
    return patched


if __name__ == "__main__":
    total = 0
    for p in sys.argv[1:]:
        n = patch(p)
        print(f"{p}: {n} line(s) patched")
        total += n
    print(f"total: {total}")
