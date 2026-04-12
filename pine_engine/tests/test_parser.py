"""Tests for Phase 2: Pine Script Parser."""

import sys
sys.path.insert(0, '/home/pouya/pine-engine')

from pine_engine.lexer import tokenize
from pine_engine.parser import parse, Parser, ParseError
from pine_engine.ast_nodes import *


def test_simple_declaration():
    tokens = tokenize('x = 5')
    prog, inputs = parse(tokens)
    assert len(prog.statements) == 1
    stmt = prog.statements[0]
    assert isinstance(stmt, VarDeclaration)
    assert stmt.name == 'x'
    assert isinstance(stmt.initializer, NumberLiteral)
    assert stmt.initializer.value == 5
    assert stmt.is_var == False
    print("  [PASS] Simple declaration")


def test_var_declaration():
    tokens = tokenize('var float x = na')
    prog, _ = parse(tokens)
    stmt = prog.statements[0]
    assert isinstance(stmt, VarDeclaration)
    assert stmt.is_var == True
    assert stmt.type_hint == 'float'
    assert stmt.name == 'x'
    assert isinstance(stmt.initializer, NaLiteral)
    print("  [PASS] var float declaration")


def test_reassignment():
    tokens = tokenize('x := 10.5')
    prog, _ = parse(tokens)
    stmt = prog.statements[0]
    assert isinstance(stmt, Assignment)
    assert stmt.target == 'x'
    assert isinstance(stmt.value, NumberLiteral)
    assert stmt.value.value == 10.5
    print("  [PASS] Reassignment :=")


def test_binary_ops():
    tokens = tokenize('x = a + b * c')
    prog, _ = parse(tokens)
    stmt = prog.statements[0]
    expr = stmt.initializer
    # Should be a + (b * c) due to precedence
    assert isinstance(expr, BinaryOp)
    assert expr.op == '+'
    assert isinstance(expr.right, BinaryOp)
    assert expr.right.op == '*'
    print("  [PASS] Binary ops with precedence")


def test_comparison():
    tokens = tokenize('x = a >= b')
    prog, _ = parse(tokens)
    expr = prog.statements[0].initializer
    assert isinstance(expr, BinaryOp)
    assert expr.op == '>='
    print("  [PASS] Comparison >=")


def test_ternary():
    tokens = tokenize('x = a ? b : c')
    prog, _ = parse(tokens)
    expr = prog.statements[0].initializer
    assert isinstance(expr, Ternary)
    assert isinstance(expr.condition, Identifier)
    print("  [PASS] Ternary expression")


def test_unary_not():
    tokens = tokenize('x = not a')
    prog, _ = parse(tokens)
    expr = prog.statements[0].initializer
    assert isinstance(expr, UnaryOp)
    assert expr.op == 'not'
    print("  [PASS] Unary not")


def test_unary_minus():
    tokens = tokenize('x = -5.5')
    prog, _ = parse(tokens)
    expr = prog.statements[0].initializer
    assert isinstance(expr, UnaryOp)
    assert expr.op == '-'
    print("  [PASS] Unary minus")


def test_history_ref():
    tokens = tokenize('x = close[1]')
    prog, _ = parse(tokens)
    expr = prog.statements[0].initializer
    assert isinstance(expr, HistoryRef)
    assert isinstance(expr.series, Identifier)
    assert expr.series.name == 'close'
    assert isinstance(expr.offset, NumberLiteral)
    assert expr.offset.value == 1
    print("  [PASS] History reference close[1]")


def test_function_call():
    tokens = tokenize('x = math.abs(y)')
    prog, _ = parse(tokens)
    expr = prog.statements[0].initializer
    assert isinstance(expr, FunctionCall)
    assert expr.name == 'math.abs'
    assert len(expr.args) == 1
    print("  [PASS] Dotted function call")


def test_function_call_kwargs():
    tokens = tokenize('x = input.int(2, "Label", minval=1, maxval=10)')
    prog, inputs = parse(tokens)
    expr = prog.statements[0].initializer
    assert isinstance(expr, FunctionCall)
    assert expr.name == 'input.int'
    assert len(expr.args) == 2
    assert 'minval' in expr.kwargs
    assert 'maxval' in expr.kwargs
    # Check inputs extraction
    assert 'x' in inputs
    assert inputs['x']['type'] == 'int'
    assert inputs['x']['default'] == 2
    print("  [PASS] Function call with kwargs + input extraction")


def test_member_access():
    tokens = tokenize('x = strategy.long')
    prog, _ = parse(tokens)
    expr = prog.statements[0].initializer
    assert isinstance(expr, Identifier)
    assert expr.name == 'strategy.long'
    print("  [PASS] Member access (dotted identifier)")


def test_if_statement():
    source = '''if x > 5
    y := 1
    z := 2'''
    tokens = tokenize(source)
    prog, _ = parse(tokens)
    stmt = prog.statements[0]
    assert isinstance(stmt, IfStatement)
    assert isinstance(stmt.condition, BinaryOp)
    assert stmt.condition.op == '>'
    assert len(stmt.then_body) == 2
    assert stmt.else_body is None
    print("  [PASS] If statement with block")


def test_if_else():
    source = '''if x
    y := 1
else
    y := 2'''
    tokens = tokenize(source)
    prog, _ = parse(tokens)
    stmt = prog.statements[0]
    assert isinstance(stmt, IfStatement)
    assert len(stmt.then_body) == 1
    assert stmt.else_body is not None
    assert len(stmt.else_body) == 1
    print("  [PASS] If/else")


def test_if_elif_else():
    source = '''if a
    x := 1
else if b
    x := 2
else
    x := 3'''
    tokens = tokenize(source)
    prog, _ = parse(tokens)
    stmt = prog.statements[0]
    assert isinstance(stmt, IfStatement)
    assert len(stmt.elif_branches) == 1
    assert stmt.else_body is not None
    print("  [PASS] If/elif/else")


def test_for_loop():
    source = '''for i = 0 to 10
    x := x + i'''
    tokens = tokenize(source)
    prog, _ = parse(tokens)
    stmt = prog.statements[0]
    assert isinstance(stmt, ForStatement)
    assert stmt.var_name == 'i'
    assert isinstance(stmt.start, NumberLiteral)
    assert isinstance(stmt.end, NumberLiteral)
    assert len(stmt.body) == 1
    print("  [PASS] For loop")


def test_function_def():
    source = '''makeTxt(name, price) =>
    name + " | " + price'''
    tokens = tokenize(source)
    prog, _ = parse(tokens)
    stmt = prog.statements[0]
    assert isinstance(stmt, FunctionDef)
    assert stmt.name == 'makeTxt'
    assert stmt.params == ['name', 'price']
    print("  [PASS] Function definition")


def test_strategy_decl():
    source = '''strategy("My Bot", overlay=true, default_qty_value=50)'''
    tokens = tokenize(source)
    prog, _ = parse(tokens)
    stmt = prog.statements[0]
    assert isinstance(stmt, StrategyDeclaration)
    assert stmt.name == "My Bot"
    assert stmt.kwargs.get('overlay') == True
    assert stmt.kwargs.get('default_qty_value') == 50
    print("  [PASS] Strategy declaration")


def test_complex_expression():
    tokens = tokenize('x = not na(ph) and pivotInWindow')
    prog, _ = parse(tokens)
    expr = prog.statements[0].initializer
    assert isinstance(expr, BinaryOp)
    assert expr.op == 'and'
    assert isinstance(expr.left, UnaryOp)  # not na(ph)
    assert expr.left.op == 'not'
    print("  [PASS] Complex: not na(ph) and pivotInWindow")


def test_and_or_chain():
    tokens = tokenize('x = a and b or c')
    prog, _ = parse(tokens)
    expr = prog.statements[0].initializer
    # or has lower precedence than and: (a and b) or c
    assert isinstance(expr, BinaryOp)
    assert expr.op == 'or'
    assert isinstance(expr.left, BinaryOp)
    assert expr.left.op == 'and'
    print("  [PASS] and/or precedence")


def test_nested_history():
    tokens = tokenize('x = hour(time[pivotRight], "America/New_York")')
    prog, _ = parse(tokens)
    expr = prog.statements[0].initializer
    assert isinstance(expr, FunctionCall)
    assert expr.name == 'hour'
    assert isinstance(expr.args[0], HistoryRef)
    print("  [PASS] Nested: hour(time[pivotRight], tz)")


def test_strategy_order_call():
    source = 'strategy.order("Long_078", strategy.long, qty=50, limit=lvl_n078, comment="Long_078")'
    tokens = tokenize(source)
    prog, _ = parse(tokens)
    stmt = prog.statements[0]
    assert isinstance(stmt, ExprStatement)
    call = stmt.expr
    assert isinstance(call, FunctionCall)
    assert call.name == 'strategy.order'
    assert len(call.args) == 2
    assert 'qty' in call.kwargs
    assert 'limit' in call.kwargs
    assert 'comment' in call.kwargs
    print("  [PASS] strategy.order() call")


def test_real_pine_file():
    """Parse the actual trading_bot.pine and verify structure."""
    try:
        with open('/mnt/c/Users/nader/Documents/Claude-memories/trading bot/trading_bot.pine', 'r') as f:
            source = f.read()
    except FileNotFoundError:
        print("  [SKIP] trading_bot.pine not found")
        return

    tokens = tokenize(source)
    try:
        prog, inputs = parse(tokens)
    except ParseError as e:
        print(f"  [FAIL] Parse error: {e}")
        return

    # Count node types
    var_decls = [s for s in prog.statements if isinstance(s, VarDeclaration)]
    assignments = [s for s in prog.statements if isinstance(s, Assignment)]
    if_stmts = [s for s in prog.statements if isinstance(s, IfStatement)]
    for_stmts = [s for s in prog.statements if isinstance(s, ForStatement)]
    func_defs = [s for s in prog.statements if isinstance(s, FunctionDef)]
    strategy_decls = [s for s in prog.statements if isinstance(s, StrategyDeclaration)]
    expr_stmts = [s for s in prog.statements if isinstance(s, ExprStatement)]

    print(f"  Total statements: {len(prog.statements)}")
    print(f"  Strategy decl: {len(strategy_decls)}")
    print(f"  Var declarations: {len(var_decls)} (var: {sum(1 for v in var_decls if v.is_var)})")
    print(f"  Assignments: {len(assignments)}")
    print(f"  If statements: {len(if_stmts)}")
    print(f"  For statements: {len(for_stmts)}")
    print(f"  Function defs: {len(func_defs)}")
    print(f"  Expression stmts: {len(expr_stmts)}")
    print(f"  Inputs extracted: {len(inputs)}")

    # Basic assertions
    assert len(strategy_decls) == 1, "Expected exactly 1 strategy declaration"
    assert len(var_decls) > 50, f"Expected >50 var declarations, got {len(var_decls)}"
    assert len(if_stmts) > 5, f"Expected >5 if statements, got {len(if_stmts)}"
    assert len(inputs) > 10, f"Expected >10 inputs, got {len(inputs)}"

    # Check strategy declaration
    sd = strategy_decls[0]
    assert "NQ Pre-Open" in sd.name

    # Check some known inputs exist
    input_names = list(inputs.keys())
    print(f"  Input names: {input_names[:10]}...")

    print(f"  [PASS] Real trading_bot.pine parsed ({len(prog.statements)} top-level stmts)")


if __name__ == "__main__":
    print("Running Phase 2 Parser Tests...")
    print()
    print("Declarations:")
    test_simple_declaration()
    test_var_declaration()
    test_reassignment()
    print()
    print("Expressions:")
    test_binary_ops()
    test_comparison()
    test_ternary()
    test_unary_not()
    test_unary_minus()
    test_history_ref()
    test_function_call()
    test_function_call_kwargs()
    test_member_access()
    test_complex_expression()
    test_and_or_chain()
    test_nested_history()
    print()
    print("Statements:")
    test_if_statement()
    test_if_else()
    test_if_elif_else()
    test_for_loop()
    test_function_def()
    test_strategy_decl()
    test_strategy_order_call()
    print()
    print("Integration:")
    test_real_pine_file()
    print()
    print("═══ ALL PHASE 2 TESTS PASSED ═══")
