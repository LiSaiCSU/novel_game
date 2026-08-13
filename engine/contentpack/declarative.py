"""Small deterministic rule language for untrusted creator content.

The evaluator walks validated data.  It never evaluates source code and has no
I/O capabilities.  Runtime limits make deeply nested or deliberately expensive
creator expressions fail closed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class RuleLanguageError(ValueError):
    pass


class Expression(BaseModel):
    model_config = ConfigDict(extra="forbid")

    op: str
    args: list[Any] = Field(default_factory=list, max_length=16)

    @model_validator(mode="after")
    def allowed_operation(self) -> Expression:
        if self.op not in ALLOWED_OPERATIONS:
            raise ValueError(f"unsupported declarative operation: {self.op}")
        return self


ALLOWED_OPERATIONS = frozenset(
    {
        "literal",
        "get",
        "and",
        "or",
        "not",
        "eq",
        "ne",
        "gt",
        "gte",
        "lt",
        "lte",
        "add",
        "sub",
        "mul",
        "div",
        "min",
        "max",
        "clamp",
        "in",
    }
)

ALLOWED_EFFECTS = frozenset(
    {
        "set_player_data",
        "adjust_player_resource",
        "relationship_delta",
        "inventory_add",
        "inventory_remove",
        "quest_status",
        "plot_thread_update",
        "location_flag",
    }
)


class RuleEffect(BaseModel):
    """A bounded canonical write operation; arbitrary paths are never accepted."""

    model_config = ConfigDict(extra="forbid")

    op: str
    target: str = "player"
    field: str = ""
    value: Any = None
    values: dict[str, Any] = Field(default_factory=dict, max_length=16)
    quantity: Any = 1

    @model_validator(mode="after")
    def valid_effect(self) -> RuleEffect:
        if self.op not in ALLOWED_EFFECTS:
            raise ValueError(f"unsupported declarative effect: {self.op}")
        if self.op in {"set_player_data", "adjust_player_resource"} and not self.field:
            raise ValueError(f"{self.op} requires field")
        if self.op in {"relationship_delta", "plot_thread_update", "location_flag"} and not self.values:
            raise ValueError(f"{self.op} requires values")
        if self.op == "set_player_data":
            parts = self.field.split(".")
            if len(parts) != 2 or parts[0] not in {"attributes", "resources", "progressions", "properties"}:
                raise ValueError("set_player_data field must be a writable player namespace and key")
        if self.op == "relationship_delta" and not set(self.values) <= {
            "affection", "trust", "respect", "fear", "hatred", "suspicion",
            "dependency", "familiarity", "boundaries",
        }:
            raise ValueError("relationship_delta contains an unsupported dimension")
        if self.op == "plot_thread_update" and not set(self.values) <= {
            "status", "stage", "next_beat_hint", "escalation_pressure",
        }:
            raise ValueError("plot_thread_update contains an unsupported field")
        if self.op == "location_flag" and any(
            not key or key.startswith("_") or "__" in key for key in self.values
        ):
            raise ValueError("location_flag contains an unsafe field")
        return self


class DeclarativeRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(pattern=r"^[a-z][a-z0-9_]{1,79}$")
    trigger: Literal["after_action"] = "after_action"
    condition: Any = True
    effects: list[RuleEffect] = Field(min_length=1, max_length=16)

    @field_validator("condition")
    @classmethod
    def condition_is_bounded(cls, value: Any) -> Any:
        validate_expression_structure(value)
        return value

    @model_validator(mode="after")
    def expressions_are_bounded(self) -> DeclarativeRule:
        for effect in self.effects:
            validate_expression_structure(effect.value)
            validate_expression_structure(effect.quantity)
            for value in effect.values.values():
                validate_expression_structure(value)
        return self


@dataclass(slots=True)
class EvaluationBudget:
    remaining: int = 256
    max_depth: int = 16

    def spend(self, depth: int) -> None:
        if depth > self.max_depth:
            raise RuleLanguageError("declarative expression exceeds maximum depth")
        self.remaining -= 1
        if self.remaining < 0:
            raise RuleLanguageError("declarative expression exceeds operation budget")


def validate_expression_structure(raw: Any, budget: EvaluationBudget | None = None, depth: int = 0) -> None:
    """Validate every nested operator without executing creator data."""
    active = budget or EvaluationBudget()
    active.spend(depth)
    if not isinstance(raw, dict):
        return
    expr = Expression.model_validate(raw)
    if expr.op == "get":
        if len(expr.args) != 1 or not isinstance(expr.args[0], str):
            raise RuleLanguageError("get expects one string path")
        path = expr.args[0]
        if not path or path.startswith("_") or "__" in path:
            raise RuleLanguageError("unsafe context path")
        return
    for item in expr.args:
        validate_expression_structure(item, active, depth + 1)


def _lookup(context: dict[str, Any], path: str) -> Any:
    if not path or path.startswith("_") or "__" in path:
        raise RuleLanguageError("unsafe context path")
    node: Any = context
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def evaluate(raw: Expression | dict[str, Any] | Any, context: dict[str, Any]) -> Any:
    return _evaluate(raw, context, EvaluationBudget(), 0)


def _evaluate(
    raw: Expression | dict[str, Any] | Any,
    context: dict[str, Any],
    budget: EvaluationBudget,
    depth: int,
) -> Any:
    budget.spend(depth)
    if not isinstance(raw, (Expression, dict)):
        return raw
    expr = raw if isinstance(raw, Expression) else Expression.model_validate(raw)
    values = [_evaluate(arg, context, budget, depth + 1) for arg in expr.args]
    op = expr.op

    if op == "literal":
        return expr.args[0] if expr.args else None
    if op == "get":
        if len(expr.args) != 1 or not isinstance(expr.args[0], str):
            raise RuleLanguageError("get expects one string path")
        return _lookup(context, expr.args[0])
    if op == "and":
        return all(bool(value) for value in values)
    if op == "or":
        return any(bool(value) for value in values)
    if op == "not":
        return not bool(_one(values, op))
    if op in {"eq", "ne", "gt", "gte", "lt", "lte"}:
        left, right = _two(values, op)
        return {
            "eq": lambda: left == right,
            "ne": lambda: left != right,
            "gt": lambda: left > right,
            "gte": lambda: left >= right,
            "lt": lambda: left < right,
            "lte": lambda: left <= right,
        }[op]()
    if op == "add":
        return sum(_number(value) for value in values)
    if op == "sub":
        left, right = _two(values, op)
        return _number(left) - _number(right)
    if op == "mul":
        result = 1.0
        for value in values:
            result *= _number(value)
        return result
    if op == "div":
        left, right = _two(values, op)
        divisor = _number(right)
        if divisor == 0:
            raise RuleLanguageError("division by zero")
        return _number(left) / divisor
    if op == "min":
        return min(_number(value) for value in values)
    if op == "max":
        return max(_number(value) for value in values)
    if op == "clamp":
        value, minimum, maximum = _three(values, op)
        return max(_number(minimum), min(_number(maximum), _number(value)))
    if op == "in":
        needle, haystack = _two(values, op)
        return needle in haystack if isinstance(haystack, (list, tuple, set, str)) else False
    raise RuleLanguageError(f"unsupported operation: {op}")


def _number(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RuleLanguageError("numeric operation received a non-number")
    return float(value)


def _one(values: list[Any], op: str) -> Any:
    if len(values) != 1:
        raise RuleLanguageError(f"{op} expects one argument")
    return values[0]


def _two(values: list[Any], op: str) -> tuple[Any, Any]:
    if len(values) != 2:
        raise RuleLanguageError(f"{op} expects two arguments")
    return values[0], values[1]


def _three(values: list[Any], op: str) -> tuple[Any, Any, Any]:
    if len(values) != 3:
        raise RuleLanguageError(f"{op} expects three arguments")
    return values[0], values[1], values[2]
