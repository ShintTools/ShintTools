"""
Tree-sitter parser for C# code.

Mirrors the public interface of ``CppParser`` so the Unity csharp rule
modules can extract method bodies via a real AST instead of the
brace-walking regex in ``_csharp_helpers._update_body``.

The C# grammar ships through ``tree_sitter_languages`` (which bundles
``tree_sitter_c_sharp``). When that dependency is absent the constructor
raises ``ImportError`` and the callers fall back to the regex helper —
ShintTools must keep working with zero extra dependencies installed.
"""

from typing import Any, Optional

# tree_sitter_languages bundles the compiled C# grammar. Importing it at
# module load lets a missing dependency surface as a plain ImportError
# the callers already know how to swallow.
from tree_sitter_languages import get_language, get_parser  # noqa: F401

# Unity polls Update / LateUpdate / FixedUpdate identically, so a rule
# that says "X inside Update" must also inspect the other two bodies.
_UPDATE_ALIASES = ("Update", "LateUpdate", "FixedUpdate")


def _node_name(node: Any) -> str:
    """Return the text of a method_declaration's name identifier.

    The grammar emits the method name as a direct ``identifier`` child of
    the ``method_declaration`` node (modifiers / return type precede it,
    the parameter_list follows). Returns '' when not found.
    """
    for child in node.children:
        if child.type == "identifier":
            return child.text.decode("utf-8") if child.text else ""
    return ""


class CsharpParser:
    """Parses C# code using Tree-sitter.

    Public surface intentionally matches ``CppParser``:
      * ``parse(source) -> tree``
      * ``find_function_body(tree, name) -> Node | None``
    """

    def __init__(self) -> None:
        """Initialize the parser.

        Handles both tree-sitter API versions the same way CppParser
        does. ``tree_sitter_languages`` already returns ready-made
        Language / Parser objects, but we still guard the call so a
        future API shift degrades to the ImportError fallback rather
        than crashing the validator.
        """
        try:
            # tree_sitter_languages >= current: returns a Parser bound
            # to the C# grammar directly.
            self.parser = get_parser("c_sharp")
        except Exception as exc:  # pragma: no cover - defensive
            # Surface as ImportError so the rule modules treat it the
            # same as a missing dependency and fall back to regex.
            raise ImportError(f"tree_sitter C# grammar unavailable: {exc}") from exc

    def parse(self, source: str) -> Any:
        """Parse source and return the root node (mirrors CppParser)."""
        src_bytes = source.encode("utf-8") if isinstance(source, str) else source
        return self.parser.parse(src_bytes).root_node

    def find_function_body(
        self,
        tree: Any,
        function_name: str,
    ) -> Optional[Any]:
        """Find a method by name and return its ``block`` body node.

        Searches every ``method_declaration`` in the whole tree (the
        target may live inside a nested class), and returns the ``block``
        child of the first method whose name matches. When
        ``function_name == "Update"`` LateUpdate / FixedUpdate also
        match, since Unity polls all three on the frame path.
        """
        targets: tuple[str, ...] = (
            _UPDATE_ALIASES if function_name == "Update" else (function_name,)
        )

        for node in self._traverse(tree):
            if node.type != "method_declaration":
                continue
            if _node_name(node) in targets:
                body = self._find_child(node, "block")
                if body is not None:
                    return body
        return None

    # ── internals ────────────────────────────────────────────────────

    def _traverse(self, node: Any):
        """Yield every node in the tree, depth-first."""
        yield node
        for child in node.children:
            yield from self._traverse(child)

    def _find_child(self, node: Any, child_type: str) -> Optional[Any]:
        """Return the first direct child of ``child_type``."""
        for child in node.children:
            if child.type == child_type:
                return child
        return None
