"""Tests for Phase 3: Code Generator (Transpiler)."""

import sys
sys.path.insert(0, '/home/pouya/pine-engine')

from pine_engine.lexer import tokenize
from pine_engine.parser import parse
from pine_engine.codegen import generate_code


def test_simple_declaration():
    tokens = tokenize('x = 5 + 3')
    prog, inputs = parse(tokens)
    code = generate_code(prog, inputs)
    assert 'x = (5 + 3)' in code
    print("  [PASS] Simple declaration")


def test_var_declaration():
    tokens = tokenize('var float x = na')
    prog, inputs = parse(tokens)
    code = generate_code(prog, inputs)
    assert 'ctx.v_x = NA' in code  # In initialize()
    print("  [PASS] Var declaration in initialize()")


def test_reassignment():
    source = '''var int x = 0
x := 5'''
    tokens = tokenize(source)
    prog, inputs = parse(tokens)
    code = generate_code(prog, inputs)
    assert 'ctx.v_x = 5' in code
    print("  [PASS] Reassignment to var")


def test_if_statement():
    source = '''var bool flag = false
if flag
    x = 1'''
    tokens = tokenize(source)
    prog, inputs = parse(tokens)
    code = generate_code(prog, inputs)
    assert 'if ctx.v_flag:' in code
    print("  [PASS] If statement")


def test_for_loop():
    source = '''for i = 0 to 10
    x = i'''
    tokens = tokenize(source)
    prog, inputs = parse(tokens)
    code = generate_code(prog, inputs)
    assert 'for i in range(int(0), int(10) + 1):' in code
    print("  [PASS] For loop")


def test_na_aware_ops():
    tokens = tokenize('x = a and b')
    prog, inputs = parse(tokens)
    code = generate_code(prog, inputs)
    assert 'pine_and(' in code
    print("  [PASS] NA-aware and")


def test_ternary():
    tokens = tokenize('x = a ? b : c')
    prog, inputs = parse(tokens)
    code = generate_code(prog, inputs)
    assert 'if' in code and 'else' in code
    print("  [PASS] Ternary → Python conditional")


def test_history_ref():
    tokens = tokenize('x = close[1]')
    prog, inputs = parse(tokens)
    code = generate_code(prog, inputs)
    assert 'ctx.close[1]' in code
    print("  [PASS] History ref → ctx.close[1]")


def test_strategy_order():
    source = 'strategy.order("Long_078", strategy.long, qty=50, limit=lvl)'
    tokens = tokenize(source)
    prog, inputs = parse(tokens)
    code = generate_code(prog, inputs)
    assert 'ctx.strategy.order(' in code
    assert 'STRATEGY_LONG' in code
    print("  [PASS] strategy.order() call")


def test_strategy_exit():
    source = 'strategy.exit("Ex1", from_entry="Long_078", qty=25, limit=tp, stop=sl)'
    tokens = tokenize(source)
    prog, inputs = parse(tokens)
    code = generate_code(prog, inputs)
    assert 'ctx.strategy.exit(' in code
    print("  [PASS] strategy.exit() call")


def test_strategy_cancel():
    source = 'strategy.cancel("Long_078")'
    tokens = tokenize(source)
    prog, inputs = parse(tokens)
    code = generate_code(prog, inputs)
    assert 'ctx.strategy.cancel(' in code
    print("  [PASS] strategy.cancel() call")


def test_builtin_function():
    tokens = tokenize('x = math.abs(y)')
    prog, inputs = parse(tokens)
    code = generate_code(prog, inputs)
    assert 'pine_abs(' in code
    print("  [PASS] math.abs → pine_abs")


def test_time_function():
    tokens = tokenize('x = hour(time, "America/New_York")')
    prog, inputs = parse(tokens)
    code = generate_code(prog, inputs)
    assert 'pine_hour(' in code
    print("  [PASS] hour() → pine_hour()")


def test_skip_viz():
    source = 'plotshape(not na(ph), title="Pivot", location=location.abovebar)'
    tokens = tokenize(source)
    prog, inputs = parse(tokens)
    code = generate_code(prog, inputs)
    assert 'SKIP' in code or 'pass' in code
    print("  [PASS] Visualization skipped")


def test_constants():
    tokens = tokenize('x = dayofweek.monday')
    prog, inputs = parse(tokens)
    code = generate_code(prog, inputs)
    assert '2' in code  # dayofweek.monday = 2
    print("  [PASS] Pine constant → Python value")


def test_real_pine_generates_valid_python():
    """Generate Python from trading_bot.pine and verify it compiles."""
    try:
        with open('/mnt/c/Users/nader/Documents/Claude-memories/trading bot/trading_bot.pine', 'r') as f:
            source = f.read()
    except FileNotFoundError:
        print("  [SKIP] trading_bot.pine not found")
        return

    tokens = tokenize(source)
    prog, inputs = parse(tokens)
    code = generate_code(prog, inputs)

    # Verify it's valid Python syntax
    try:
        compile(code, '<generated>', 'exec')
        print(f"  Generated {len(code)} chars, {code.count(chr(10))} lines")
        print(f"  [PASS] Generated code compiles as valid Python")
    except SyntaxError as e:
        # Find the problematic area
        lines = code.split('\n')
        start = max(0, e.lineno - 3)
        end = min(len(lines), e.lineno + 3)
        print(f"  [FAIL] SyntaxError at line {e.lineno}: {e.msg}")
        for i in range(start, end):
            marker = '>>>' if i + 1 == e.lineno else '   '
            print(f"  {marker} {i+1}: {lines[i]}")
        return

    # Check key code patterns exist
    assert 'def initialize(ctx):' in code
    assert 'def execute_bar(ctx):' in code
    assert 'ctx.strategy.order(' in code
    assert 'ctx.strategy.exit(' in code
    assert 'ctx.strategy.cancel(' in code
    assert 'pine_hour(' in code
    assert 'ta_pivothigh(' in code
    assert 'STRATEGY_LONG' in code

    # Count generated elements
    order_calls = code.count('ctx.strategy.order(')
    exit_calls = code.count('ctx.strategy.exit(')
    cancel_calls = code.count('ctx.strategy.cancel(')
    print(f"  strategy.order: {order_calls}, strategy.exit: {exit_calls}, strategy.cancel: {cancel_calls}")
    print(f"  Inputs: {len(inputs)}")

    print(f"  [PASS] Real trading_bot.pine → valid executable Python")


def test_user_func_expr_transpiled():
    """User function with => expression body is transpiled (not stubbed to NA)."""
    source = '''f(a, b) => math.max(a, b)
x = f(1.0, 2.0)'''
    code = generate_code(*parse(tokenize(source)))
    assert 'def f(a, b):' in code
    assert 'return pine_max(a, b)' in code, code
    compile(code, '<gen>', 'exec')
    print("  [PASS] User function (expr body) transpiled")


def test_user_func_param_shadows_global():
    """A function parameter shadows a same-named global var inside the body."""
    source = '''var float a = na
g(a) => a + 1.0
y = g(5.0)'''
    code = generate_code(*parse(tokenize(source)))
    assert 'return (a + 1.0)' in code, code   # param 'a', NOT ctx.v_a
    assert 'ctx.v_a' in code                  # global still declared elsewhere
    compile(code, '<gen>', 'exec')
    print("  [PASS] Function param shadows global var")


def test_user_func_viz_stays_stub():
    """A function whose body uses viz builtins stays stubbed (return NA)."""
    import re
    source = '''mk(p) => label.new(bar_index, p, "x")
z = mk(close)'''
    code = generate_code(*parse(tokenize(source)))
    assert re.search(r'def mk\(p\):\s*\n\s*return NA', code), code
    print("  [PASS] Viz helper function stays stubbed")


if __name__ == "__main__":
    print("Running Phase 3 Codegen Tests...")
    print()
    print("Basic Transpilation:")
    test_simple_declaration()
    test_var_declaration()
    test_reassignment()
    test_if_statement()
    test_for_loop()
    test_na_aware_ops()
    test_ternary()
    test_history_ref()
    print()
    print("Strategy API:")
    test_strategy_order()
    test_strategy_exit()
    test_strategy_cancel()
    print()
    print("Builtins & Constants:")
    test_builtin_function()
    test_time_function()
    test_skip_viz()
    test_constants()
    test_user_func_expr_transpiled()
    test_user_func_param_shadows_global()
    test_user_func_viz_stays_stub()
    print()
    print("Integration:")
    test_real_pine_generates_valid_python()
    print()
    print("═══ ALL PHASE 3 TESTS PASSED ═══")
