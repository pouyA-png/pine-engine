"""AST node definitions for Pine Script v5.

~20 node types covering the language subset used by the trading bot:
  - Declarations (var, standard)
  - Assignments (:=)
  - Control flow (if/else, for/to, break)
  - Expressions (binary, unary, ternary, history ref, function call)
  - Literals (number, string, bool, na)
  - Function definitions (=>)
  - Strategy/indicator declarations
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Union


# ═══════════════════════════════════════════════════════════════════════════════
# TOP-LEVEL
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class Program:
    """Root node — list of top-level statements."""
    statements: List[Statement]
    pragma: Optional[str] = None  # e.g., "//@version=5"


@dataclass
class StrategyDeclaration:
    """strategy("name", param=value, ...) at top of file."""
    name: str
    kwargs: Dict[str, Any] = field(default_factory=dict)


@dataclass
class IndicatorDeclaration:
    """indicator("name", param=value, ...) at top of file."""
    name: str
    kwargs: Dict[str, Any] = field(default_factory=dict)


# ═══════════════════════════════════════════════════════════════════════════════
# STATEMENTS
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class VarDeclaration:
    """Variable declaration: [var] [type] name = expr"""
    name: str
    initializer: Expr
    is_var: bool = False       # var keyword — persistent across bars
    is_varip: bool = False     # varip keyword
    type_hint: Optional[str] = None  # "int", "float", "bool", "string", etc.


@dataclass
class Assignment:
    """Reassignment: target := value"""
    target: str
    value: Expr


@dataclass
class IfStatement:
    """if/else if/else block."""
    condition: Expr
    then_body: List[Statement]
    elif_branches: List[tuple]  # List of (condition, body) tuples
    else_body: Optional[List[Statement]] = None


@dataclass
class ForStatement:
    """for var_name = start to end [by step] ... body"""
    var_name: str
    start: Expr
    end: Expr
    body: List[Statement]
    step: Optional[Expr] = None


@dataclass
class BreakStatement:
    """break inside for loop."""
    pass


@dataclass
class WhileStatement:
    """while condition ... body (only used in viz code)."""
    condition: Expr
    body: List[Statement]


@dataclass
class FunctionDef:
    """User function: name(params) => expr_or_block"""
    name: str
    params: List[str]
    body: Union[Expr, List[Statement]]  # Single expr for =>, block for multi-line


@dataclass
class ExprStatement:
    """Expression used as a statement (function calls, etc.)."""
    expr: Expr


# ═══════════════════════════════════════════════════════════════════════════════
# EXPRESSIONS
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class BinaryOp:
    """Binary operation: left op right"""
    left: Expr
    op: str         # +, -, *, /, %, ==, !=, <, >, <=, >=, and, or
    right: Expr


@dataclass
class UnaryOp:
    """Unary operation: op operand"""
    op: str         # -, not
    operand: Expr


@dataclass
class Ternary:
    """Ternary: condition ? true_expr : false_expr"""
    condition: Expr
    true_expr: Expr
    false_expr: Expr


@dataclass
class HistoryRef:
    """History access: series[offset]"""
    series: Expr
    offset: Expr


@dataclass
class FunctionCall:
    """Function call: name(args, kwargs)
    Name can be dotted: strategy.order, ta.pivothigh, math.abs, etc.
    """
    name: str               # Full dotted name as string
    args: List[Expr] = field(default_factory=list)
    kwargs: Dict[str, Expr] = field(default_factory=dict)


@dataclass
class MemberAccess:
    """Member access: object.member (when not a function call)."""
    object: Expr
    member: str


@dataclass
class Identifier:
    """Variable reference."""
    name: str


@dataclass
class NumberLiteral:
    """Integer or float literal."""
    value: Union[int, float]


@dataclass
class StringLiteral:
    """String literal."""
    value: str


@dataclass
class BoolLiteral:
    """true or false."""
    value: bool


@dataclass
class NaLiteral:
    """Pine's na value."""
    pass


# Type aliases
Expr = Union[BinaryOp, UnaryOp, Ternary, HistoryRef, FunctionCall,
             MemberAccess, Identifier, NumberLiteral, StringLiteral,
             BoolLiteral, NaLiteral]

Statement = Union[VarDeclaration, Assignment, IfStatement, ForStatement,
                  WhileStatement, BreakStatement, FunctionDef, ExprStatement,
                  StrategyDeclaration, IndicatorDeclaration]
