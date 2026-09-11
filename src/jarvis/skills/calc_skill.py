"""计算技能：安全地求值数学表达式。

带参数的工具，用来演示"模型填参 → 本地执行"的完整链路。
求值用 AST 白名单，绝不使用 eval()。
"""

from __future__ import annotations

import ast
import math
import operator
import re
from typing import Any

from .base import Skill

_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPS = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_CONSTS = {"pi": math.pi, "e": math.e, "π": math.pi}
_FUNCS = {
    "sqrt": math.sqrt,
    "abs": abs,
    "round": round,
    "floor": math.floor,
    "ceil": math.ceil,
    "log": math.log,
    "log10": math.log10,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "pow": pow,
}

# 从自然语言里抠表达式：至少含一个运算符
_EXPR_RE = re.compile(r"[-+]?[\d.\s]*\d[\d\s.+\-*/%()^]*")
_MAX_LEN = 200
_MAX_POW = 1000


class _Unsafe(ValueError):
    pass


def _eval_node(node: ast.AST) -> float:
    if isinstance(node, ast.Expression):
        return _eval_node(node.body)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return node.value
        raise _Unsafe("只支持数字常量")
    if isinstance(node, ast.BinOp):
        op = _BIN_OPS.get(type(node.op))
        if op is None:
            raise _Unsafe(f"不支持的运算符 {type(node.op).__name__}")
        left, right = _eval_node(node.left), _eval_node(node.right)
        if op is operator.pow and abs(right) > _MAX_POW:
            raise _Unsafe("指数过大")
        return op(left, right)
    if isinstance(node, ast.UnaryOp):
        op = _UNARY_OPS.get(type(node.op))
        if op is None:
            raise _Unsafe(f"不支持的一元运算 {type(node.op).__name__}")
        return op(_eval_node(node.operand))
    if isinstance(node, ast.Name):
        if node.id in _CONSTS:
            return _CONSTS[node.id]
        raise _Unsafe(f"未知标识符 {node.id}")
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in _FUNCS:
            raise _Unsafe("只支持内置数学函数")
        if node.keywords:
            raise _Unsafe("不支持关键字参数")
        return _FUNCS[node.func.id](*[_eval_node(a) for a in node.args])
    raise _Unsafe(f"不支持的语法 {type(node).__name__}")


def _normalize(expr: str) -> str:
    return (
        expr.replace("×", "*")
        .replace("÷", "/")
        .replace("^", "**")
        .replace("，", ",")
        .replace("＝", "=")
        .strip()
        .rstrip("=？? ")
        .strip()
    )


def safe_eval(expr: str) -> float:
    """求值数学表达式，拒绝一切非数学语法。"""
    expr = _normalize(expr)
    if not expr:
        raise ValueError("表达式为空")
    if len(expr) > _MAX_LEN:
        raise ValueError("表达式过长")
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as e:
        raise ValueError(f"表达式语法错误: {expr}") from e
    return _eval_node(tree)


def _format(value: float) -> str:
    if isinstance(value, float) and value.is_integer() and abs(value) < 1e15:
        return str(int(value))
    return f"{value:g}"


class CalcSkill(Skill):
    name = "calculate"
    description = (
        "计算数学表达式，支持 + - * / // % ** 与 sqrt/log/sin/cos、pi、e 等。"
        "当用户需要做算术、单位换算或数值计算时使用。"
    )
    keywords = ["算", "计算", "等于", "calculate", "是多少"]
    patterns = [r"^[\d\s.+\-*/%()^=×÷,]+$", r"^算[一下]*[\d\s.+\-*/%()^=×÷,]+$"]
    parameters: dict[str, Any] = {
        "expression": {
            "type": "string",
            "description": "要计算的数学表达式，例如 (12+8)*3/sqrt(16)",
        }
    }
    required = ["expression"]

    def run(self, text: str = "", expression: str = "", **kwargs: Any) -> str:
        expr = (expression or text or "").strip()
        if not expr:
            return "请给我一个数学表达式，先生。"
        try:
            value = safe_eval(expr)
        except (ValueError, ZeroDivisionError, OverflowError, TypeError) as e:
            # 表达式里混了中文时，再试着从整句里抠一个出来
            found = _EXPR_RE.search(expr)
            if found and found.group(0).strip() != expr:
                try:
                    return f"{found.group(0).strip()} = {_format(safe_eval(found.group(0)))}"
                except (ValueError, ZeroDivisionError, OverflowError):
                    pass
            return f"算不出来，先生：{e}"
        return f"{_normalize(expr)} = {_format(value)}"
