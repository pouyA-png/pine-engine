"""Tests for Phase 1: Pine Script Lexer."""

import sys
sys.path.insert(0, '/home/pouya/pine-engine')

from pine_engine.lexer import tokenize, TokenType, Token


def test_simple_assignment():
    tokens = tokenize('x = 5')
    types = [t.type for t in tokens if t.type not in (TokenType.NEWLINE, TokenType.EOF)]
    assert types == [TokenType.IDENTIFIER, TokenType.ASSIGN, TokenType.INTEGER]
    assert tokens[0].value == 'x'
    assert tokens[2].value == '5'
    print("  [PASS] Simple assignment")


def test_var_declaration():
    tokens = tokenize('var float x = na')
    types = [t.type for t in tokens if t.type not in (TokenType.NEWLINE, TokenType.EOF)]
    assert types == [TokenType.VAR, TokenType.TYPE_FLOAT, TokenType.IDENTIFIER, TokenType.ASSIGN, TokenType.NA]
    print("  [PASS] Var declaration")


def test_reassignment():
    tokens = tokenize('x := 10.5')
    types = [t.type for t in tokens if t.type not in (TokenType.NEWLINE, TokenType.EOF)]
    assert types == [TokenType.IDENTIFIER, TokenType.REASSIGN, TokenType.FLOAT]
    print("  [PASS] Reassignment :=")


def test_operators():
    tokens = tokenize('a == b != c <= d >= e')
    ops = [t.type for t in tokens if t.type not in (TokenType.NEWLINE, TokenType.EOF, TokenType.IDENTIFIER)]
    assert ops == [TokenType.EQ, TokenType.NEQ, TokenType.LTE, TokenType.GTE]
    print("  [PASS] Comparison operators")


def test_arrow():
    tokens = tokenize('f(x) =>')
    types = [t.type for t in tokens if t.type not in (TokenType.NEWLINE, TokenType.EOF)]
    assert TokenType.ARROW in types
    print("  [PASS] Arrow =>")


def test_string_literals():
    tokens = tokenize('x = "hello"')
    strs = [t for t in tokens if t.type == TokenType.STRING]
    assert len(strs) == 1
    assert strs[0].value == 'hello'
    print("  [PASS] Double-quoted string")

    tokens = tokenize("x = 'world'")
    strs = [t for t in tokens if t.type == TokenType.STRING]
    assert len(strs) == 1
    assert strs[0].value == 'world'
    print("  [PASS] Single-quoted string")


def test_comment_handling():
    tokens = tokenize('x = 5 // this is a comment')
    types = [t.type for t in tokens if t.type not in (TokenType.NEWLINE, TokenType.EOF)]
    assert types == [TokenType.IDENTIFIER, TokenType.ASSIGN, TokenType.INTEGER]
    print("  [PASS] Inline comment stripped")


def test_pragma():
    tokens = tokenize('//@version=5')
    assert tokens[0].type == TokenType.PRAGMA
    assert tokens[0].value == '//@version=5'
    print("  [PASS] Version pragma")


def test_indentation():
    source = '''if x
    y := 1
    z := 2
a := 3'''
    tokens = tokenize(source)
    types = [t.type for t in tokens]
    assert TokenType.INDENT in types
    assert TokenType.DEDENT in types
    # Count: should have 1 INDENT after 'if x', 1 DEDENT before 'a := 3'
    indent_count = types.count(TokenType.INDENT)
    dedent_count = types.count(TokenType.DEDENT)
    assert indent_count == 1
    assert dedent_count == 1
    print("  [PASS] Indentation INDENT/DEDENT")


def test_nested_indentation():
    source = '''if a
    if b
        x := 1
    y := 2
z := 3'''
    tokens = tokenize(source)
    types = [t.type for t in tokens]
    indent_count = types.count(TokenType.INDENT)
    dedent_count = types.count(TokenType.DEDENT)
    assert indent_count == 2  # 2 levels of nesting
    assert dedent_count == 2  # back to top level
    print("  [PASS] Nested indentation")


def test_keywords():
    source = 'var if else for to break not and or true false na'
    tokens = tokenize(source)
    types = [t.type for t in tokens if t.type not in (TokenType.NEWLINE, TokenType.EOF)]
    expected = [TokenType.VAR, TokenType.IF, TokenType.ELSE, TokenType.FOR,
                TokenType.TO, TokenType.BREAK, TokenType.NOT, TokenType.AND,
                TokenType.OR, TokenType.BOOL_TRUE, TokenType.BOOL_FALSE, TokenType.NA]
    assert types == expected
    print("  [PASS] All keywords recognized")


def test_function_call():
    source = 'strategy.order("Long_078", strategy.long, qty=50, limit=lvl)'
    tokens = tokenize(source)
    types = [t.type for t in tokens if t.type not in (TokenType.NEWLINE, TokenType.EOF)]
    # strategy . order ( "Long_078" , strategy . long , qty = 50 , limit = lvl )
    expected = [
        TokenType.STRATEGY, TokenType.DOT, TokenType.IDENTIFIER, TokenType.LPAREN,
        TokenType.STRING, TokenType.COMMA,
        TokenType.STRATEGY, TokenType.DOT, TokenType.IDENTIFIER, TokenType.COMMA,
        TokenType.IDENTIFIER, TokenType.ASSIGN, TokenType.INTEGER, TokenType.COMMA,
        TokenType.IDENTIFIER, TokenType.ASSIGN, TokenType.IDENTIFIER,
        TokenType.RPAREN
    ]
    assert types == expected, f"Got: {types}"
    print("  [PASS] Function call with dotted names and named args")


def test_history_ref():
    source = 'x = close[1]'
    tokens = tokenize(source)
    types = [t.type for t in tokens if t.type not in (TokenType.NEWLINE, TokenType.EOF)]
    assert types == [TokenType.IDENTIFIER, TokenType.ASSIGN,
                     TokenType.IDENTIFIER, TokenType.LBRACKET,
                     TokenType.INTEGER, TokenType.RBRACKET]
    print("  [PASS] History reference [N]")


def test_ternary():
    source = 'x = a ? b : c'
    tokens = tokenize(source)
    types = [t.type for t in tokens if t.type not in (TokenType.NEWLINE, TokenType.EOF)]
    assert TokenType.QUESTION in types
    assert TokenType.COLON in types
    print("  [PASS] Ternary operator")


def test_color_literal():
    source = 'c = color.new(#e91e63, 0)'
    tokens = tokenize(source)
    strs = [t for t in tokens if t.type == TokenType.STRING]
    assert any('#e91e63' in s.value for s in strs)
    print("  [PASS] Color literal #hex")


def test_real_pine_file():
    """Tokenize the actual trading_bot.pine and verify basic metrics."""
    try:
        with open('/mnt/c/Users/nader/Documents/Claude-memories/trading bot/trading_bot.pine', 'r') as f:
            source = f.read()
    except FileNotFoundError:
        print("  [SKIP] trading_bot.pine not found")
        return

    tokens = tokenize(source)

    # Basic sanity checks
    assert len(tokens) > 1000, f"Expected >1000 tokens, got {len(tokens)}"

    # Check key tokens exist
    types = [t.type for t in tokens]
    assert TokenType.PRAGMA in types, "Missing //@version pragma"
    assert TokenType.STRATEGY in types or TokenType.IDENTIFIER in types, "Missing strategy"
    assert TokenType.VAR in types, "Missing var keyword"
    assert TokenType.IF in types, "Missing if keyword"
    assert TokenType.FOR in types, "Missing for keyword"
    assert TokenType.REASSIGN in types, "Missing := operator"
    assert TokenType.INDENT in types, "Missing INDENT"
    assert TokenType.DEDENT in types, "Missing DEDENT"

    # Count some specific tokens
    var_count = types.count(TokenType.VAR)
    if_count = types.count(TokenType.IF)
    for_count = types.count(TokenType.FOR)
    indent_count = types.count(TokenType.INDENT)
    dedent_count = types.count(TokenType.DEDENT)

    print(f"  Total tokens: {len(tokens)}")
    print(f"  var: {var_count}, if: {if_count}, for: {for_count}")
    print(f"  INDENT: {indent_count}, DEDENT: {dedent_count}")

    # INDENT and DEDENT should be balanced
    assert indent_count == dedent_count, \
        f"INDENT ({indent_count}) != DEDENT ({dedent_count})"

    # Should find strategy keyword tokens (strategy.order calls)
    strategy_tokens = [t for t in tokens if t.type == TokenType.STRATEGY]
    assert len(strategy_tokens) > 0, "No 'strategy' tokens found"

    print(f"  [PASS] Real trading_bot.pine tokenized ({len(tokens)} tokens, balanced indent)")


if __name__ == "__main__":
    print("Running Phase 1 Lexer Tests...")
    print()
    print("Basic Tokenization:")
    test_simple_assignment()
    test_var_declaration()
    test_reassignment()
    test_operators()
    test_arrow()
    test_string_literals()
    test_comment_handling()
    test_pragma()
    test_keywords()
    test_ternary()
    test_color_literal()
    print()
    print("Indentation:")
    test_indentation()
    test_nested_indentation()
    print()
    print("Pine-specific:")
    test_function_call()
    test_history_ref()
    print()
    print("Integration:")
    test_real_pine_file()
    print()
    print("═══ ALL PHASE 1 TESTS PASSED ═══")
