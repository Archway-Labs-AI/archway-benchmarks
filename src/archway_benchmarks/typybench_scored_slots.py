"""Source-editing identities for TypyBench's direct scoring surface.

TypyBench removes function parameter and return annotations, runs mypy, and
compares the resulting symbol-table entries.  This module describes that
potential scoring surface from the untyped source tree.  It does not infer
types and it does not inspect the typed reference answers.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from enum import StrEnum


class ScoredSlotKind(StrEnum):
    PARAMETER = "parameter"
    RETURN = "return"


@dataclass(frozen=True, slots=True)
class ScoredSlot:
    kind: ScoredSlotKind
    qualified_callable: str
    name: str
    definition_line: int
    definition_col: int
    has_annotation: bool

    @property
    def role(self) -> str:
        return "return" if self.kind is ScoredSlotKind.RETURN else f"param:{self.name}"

    @property
    def adapter_key(self) -> tuple[str, str]:
        return self.qualified_callable, self.role

    def jsonable(self) -> dict[str, object]:
        return {
            "kind": self.kind.value,
            "qualified_callable": self.qualified_callable,
            "name": self.name,
            "definition_line": self.definition_line,
            "definition_col": self.definition_col,
            "has_annotation": self.has_annotation,
            "role": self.role,
        }


class _ScoredSlotVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.scope: list[str] = []
        self.slots: list[ScoredSlot] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.scope.append(node.name)
        try:
            self.generic_visit(node)
        finally:
            self.scope.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def _visit_function(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef,
    ) -> None:
        qualified = ".".join((*self.scope, node.name))
        arguments = (
            *node.args.posonlyargs,
            *node.args.args,
            *node.args.kwonlyargs,
            *((node.args.vararg,) if node.args.vararg is not None else ()),
            *((node.args.kwarg,) if node.args.kwarg is not None else ()),
        )
        for argument in arguments:
            self.slots.append(ScoredSlot(
                kind=ScoredSlotKind.PARAMETER,
                qualified_callable=qualified,
                name=argument.arg,
                definition_line=node.lineno,
                definition_col=node.col_offset,
                has_annotation=argument.annotation is not None,
            ))
        self.slots.append(ScoredSlot(
            kind=ScoredSlotKind.RETURN,
            qualified_callable=qualified,
            name=qualified,
            definition_line=node.lineno,
            definition_col=node.col_offset,
            has_annotation=node.returns is not None,
        ))
        self.scope.append(node.name)
        try:
            self.generic_visit(node)
        finally:
            self.scope.pop()


def scored_slots(source: str) -> tuple[ScoredSlot, ...]:
    """Return potential direct scorer slots in stable source order."""

    visitor = _ScoredSlotVisitor()
    visitor.visit(ast.parse(source))
    return tuple(sorted(
        visitor.slots,
        key=lambda item: (
            item.definition_line,
            item.definition_col,
            item.qualified_callable,
            item.kind.value,
            item.name,
        ),
    ))
