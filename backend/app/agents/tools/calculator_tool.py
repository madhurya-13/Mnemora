"""Bounded arithmetic and date utilities. No eval, exec or imports."""

from __future__ import annotations

import ast
import math
import operator
from datetime import date, timedelta

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.agents.agent_schemas import ToolContext, ToolResult
from app.agents.tools.base_tool import ToolSpec
from app.agents.tools.registry import registry

_BINARY = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_MAX_ABS_RESULT = 1_000_000_000_000


class CalculatorInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expression: str | None = Field(default=None, max_length=200)
    start_date: date | None = None
    offset_days: int | None = Field(default=None, ge=-36500, le=36500)
    end_date: date | None = None

    @model_validator(mode="after")
    def exactly_one_mode(self) -> "CalculatorInput":
        arithmetic = bool(self.expression and self.expression.strip())
        dated = self.start_date is not None
        if arithmetic == dated:
            raise ValueError("Provide either an arithmetic expression or a start date.")
        if dated and self.offset_days is None and self.end_date is None:
            raise ValueError("Provide offset_days or end_date with start_date.")
        if not dated and (self.offset_days is not None or self.end_date is not None):
            raise ValueError("Date fields require start_date.")
        return self


def _evaluate(node: ast.AST) -> float:
    if isinstance(node, ast.Expression):
        return _evaluate(node.body)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise ValueError("Only numeric literals are allowed.")
        return float(node.value)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
        return _UNARY[type(node.op)](_evaluate(node.operand))
    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY:
        left = _evaluate(node.left)
        right = _evaluate(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > 12:
            raise ValueError("Exponent is limited to 12.")
        value = _BINARY[type(node.op)](left, right)
        if abs(value) > _MAX_ABS_RESULT:
            raise ValueError("Result exceeds the allowed magnitude.")
        return value
    raise ValueError("Unsupported arithmetic construct.")


def calculator(context: ToolContext, payload: CalculatorInput) -> ToolResult:
    if payload.expression:
        tree = ast.parse(payload.expression.strip(), mode="eval")
        try:
            value = _evaluate(tree)
        except ZeroDivisionError:
            return ToolResult(
                ok=False,
                summary="Division by zero is not allowed.",
                error="division_by_zero",
                error_kind="permanent",
            )
        if not math.isfinite(value):
            return ToolResult(
                ok=False,
                summary="The result is not a finite number.",
                error="non_finite_result",
                error_kind="permanent",
            )
        rendered = int(value) if float(value).is_integer() else round(value, 8)
        return ToolResult(
            ok=True,
            summary=f"{payload.expression.strip()} = {rendered}",
            data={"expression": payload.expression.strip(), "value": rendered, "verifiable": True},
        )

    assert payload.start_date is not None
    if payload.end_date is not None:
        difference = (payload.end_date - payload.start_date).days
        return ToolResult(
            ok=True,
            summary=f"{payload.end_date.isoformat()} is {difference} day(s) after {payload.start_date.isoformat()}.",
            data={
                "start_date": payload.start_date.isoformat(),
                "end_date": payload.end_date.isoformat(),
                "days": difference,
                "verifiable": True,
            },
        )
    shifted = payload.start_date + timedelta(days=payload.offset_days or 0)
    return ToolResult(
        ok=True,
        summary=f"{payload.start_date.isoformat()} {payload.offset_days:+d} day(s) is {shifted.isoformat()} ({shifted.strftime('%A')}).",
        data={
            "start_date": payload.start_date.isoformat(),
            "offset_days": payload.offset_days,
            "result_date": shifted.isoformat(),
            "weekday": shifted.strftime("%A"),
            "verifiable": True,
        },
    )


registry.register(
    ToolSpec(
        name="calculator",
        description="Evaluate bounded arithmetic and date offsets without executing code.",
        category="utility",
        permission="read_only",
        input_model=CalculatorInput,
        handler=calculator,
    )
)
