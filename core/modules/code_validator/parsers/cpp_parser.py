"""
Tree-sitter parser for C++ code.
Finds patterns and extracts information for intelligent fixes.
"""

from dataclasses import dataclass
from typing import List, Optional

import tree_sitter_cpp as tscpp
from tree_sitter import Language, Node, Parser


@dataclass
class VariableInfo:
    """Information about a variable declaration."""

    name: str
    type_name: str
    initializer: str
    line: int


@dataclass
class FunctionCallInfo:
    """Information about a function call."""

    function_name: str
    full_expression: str
    variable_assigned: Optional[str]
    line: int


class CppParser:
    """Parses C++ code using Tree-sitter."""

    def __init__(self) -> None:
        """Initialize the parser."""
        cpp_language = Language(tscpp.language())
        self.parser = Parser(cpp_language)

    def parse(self, code: str) -> Node:
        """Parse code and return the root node."""
        code_bytes = code.encode() if isinstance(code, str) else code
        return self.parser.parse(code_bytes).root_node

    def find_function_body(
        self,
        root: Node,
        func_name: str,
    ) -> Optional[Node]:
        """Find a function by name and return its body."""
        for node in self._traverse(root):
            if node.type == "function_definition":
                declarator = self._find_child(node, "function_declarator")
                if declarator:
                    name_node = self._find_identifier_in_declarator(declarator)
                    if name_node and name_node.text.decode() == func_name:
                        return self._find_child(node, "compound_statement")
        return None

    def find_calls_in_node(
        self,
        node: Node,
        function_name: str,
    ) -> List[FunctionCallInfo]:
        """Find all calls to a specific function within a node."""
        calls: List[FunctionCallInfo] = []
        for n in self._traverse(node):
            if n.type == "call_expression":
                callee = n.children[0] if n.children else None
                if callee:
                    callee_name = self._extract_function_name(callee)
                    if callee_name == function_name:
                        var_name = self._find_assigned_variable(n)
                        line = n.start_point[0] + 1
                        calls.append(
                            FunctionCallInfo(
                                function_name=function_name,
                                full_expression=n.text.decode(),
                                variable_assigned=var_name,
                                line=line,
                            )
                        )
        return calls

    def find_variable_uses(
        self,
        node: Node,
        var_name: str,
    ) -> List[int]:
        """Find all lines where a variable is used."""
        uses: List[int] = []
        for n in self._traverse(node):
            if n.type == "identifier" and n.text.decode() == var_name:
                line = n.start_point[0] + 1
                if line not in uses:
                    uses.append(line)
        return uses

    def _traverse(self, node: Node):
        """Traverse all nodes in the tree."""
        yield node
        for child in node.children:
            yield from self._traverse(child)

    def _find_child(self, node: Node, child_type: str) -> Optional[Node]:
        """Find first child of a specific type."""
        for child in node.children:
            if child.type == child_type:
                return child
        return None

    def _find_identifier_in_declarator(self, declarator: Node) -> Optional[Node]:
        """Find the function name identifier in a declarator."""
        for node in self._traverse(declarator):
            if node.type == "identifier":
                return node
            if node.type == "qualified_identifier":
                for child in reversed(node.children):
                    if child.type == "identifier":
                        return child
        return None

    def _extract_function_name(self, callee_node: Node) -> str:
        """Extract function name from a callee node."""
        if callee_node.type == "identifier":
            return callee_node.text.decode()
        if callee_node.type == "template_function":
            for child in callee_node.children:
                if child.type == "identifier":
                    return child.text.decode()
        if callee_node.type == "qualified_identifier":
            for child in reversed(callee_node.children):
                if child.type == "identifier":
                    return child.text.decode()
        return ""

    def _find_assigned_variable(self, call_node: Node) -> Optional[str]:
        """Check if a call is assigned to a variable."""
        parent = call_node.parent
        while parent:
            if parent.type == "init_declarator":
                for child in parent.children:
                    if child.type == "pointer_declarator":
                        for sub in child.children:
                            if sub.type == "identifier":
                                return sub.text.decode()
                    if child.type == "identifier":
                        return child.text.decode()
            if parent.type == "declaration":
                break
            parent = parent.parent
        return None
