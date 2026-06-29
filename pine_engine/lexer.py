"""Pine Script v5 Lexer — tokenizes .pine source into a token stream.

Handles:
  - Identifiers and keywords (var, if, else, for, to, break, not, and, or, true, false, na)
  - Numbers (int and float)
  - Strings (single and double quoted)
  - Operators (=, :=, +, -, *, /, ==, !=, <, >, <=, >=, ?, :, =>, ., [, ], (, ), ,)
  - Comments (// to end of line)
  - Indentation → INDENT/DEDENT tokens (Python-style indent stack)
  - //@version=5 pragma
"""

from __future__ import annotations
from enum import Enum, auto
from dataclasses import dataclass
from typing import List


class TokenType(Enum):
    # Literals
    INTEGER = auto()
    FLOAT = auto()
    STRING = auto()
    BOOL_TRUE = auto()
    BOOL_FALSE = auto()
    NA = auto()

    # Keywords
    VAR = auto()
    VARIP = auto()
    IF = auto()
    ELSE = auto()
    FOR = auto()
    TO = auto()
    BREAK = auto()
    NOT = auto()
    AND = auto()
    OR = auto()
    STRATEGY = auto()
    INDICATOR = auto()
    IMPORT = auto()

    # Type keywords (used in some declarations)
    TYPE_INT = auto()
    TYPE_FLOAT = auto()
    TYPE_BOOL = auto()
    TYPE_STRING = auto()
    TYPE_COLOR = auto()

    # Identifier
    IDENTIFIER = auto()

    # Operators
    ASSIGN = auto()        # =
    REASSIGN = auto()      # :=
    PLUS = auto()          # +
    MINUS = auto()         # -
    STAR = auto()          # *
    SLASH = auto()         # /
    PERCENT = auto()       # %
    EQ = auto()            # ==
    NEQ = auto()           # !=
    LT = auto()            # <
    GT = auto()            # >
    LTE = auto()           # <=
    GTE = auto()           # >=
    QUESTION = auto()      # ?
    COLON = auto()         # :
    ARROW = auto()         # =>
    DOT = auto()           # .
    COMMA = auto()         # ,

    # Brackets
    LBRACKET = auto()      # [
    RBRACKET = auto()      # ]
    LPAREN = auto()        # (
    RPAREN = auto()        # )

    # Structure
    NEWLINE = auto()
    INDENT = auto()
    DEDENT = auto()
    EOF = auto()

    # Special
    PRAGMA = auto()        # //@version=5


KEYWORDS = {
    'var': TokenType.VAR,
    'varip': TokenType.VARIP,
    'if': TokenType.IF,
    'else': TokenType.ELSE,
    'for': TokenType.FOR,
    'to': TokenType.TO,
    'break': TokenType.BREAK,
    'not': TokenType.NOT,
    'and': TokenType.AND,
    'or': TokenType.OR,
    'true': TokenType.BOOL_TRUE,
    'false': TokenType.BOOL_FALSE,
    'na': TokenType.NA,
    'strategy': TokenType.STRATEGY,
    'indicator': TokenType.INDICATOR,
    'import': TokenType.IMPORT,
    'int': TokenType.TYPE_INT,
    'float': TokenType.TYPE_FLOAT,
    'bool': TokenType.TYPE_BOOL,
    'string': TokenType.TYPE_STRING,
    'color': TokenType.TYPE_COLOR,
}


@dataclass
class Token:
    type: TokenType
    value: str
    line: int
    col: int

    def __repr__(self):
        if self.type in (TokenType.NEWLINE, TokenType.INDENT, TokenType.DEDENT, TokenType.EOF):
            return f"Token({self.type.name}, L{self.line})"
        return f"Token({self.type.name}, {self.value!r}, L{self.line})"


# ── Pine v5 line-continuation support (added 2026-06-29) ──
# Pine allows a single statement to span physical lines: inside unclosed ()/[], or when a
# line ends with / the next line begins with a binary operator. The original lexer emitted a
# NEWLINE after every physical line, so multi-line expressions (e.g. a string built with
# leading '+' on each line) broke the parser. _logical_lines() joins them first.
_CONT_START = ('+', '-', '*', '/', '%', '?', ':', ',', '.', ')', ']',
               '==', '!=', '<=', '>=', '=>', '<', '>')
_CONT_END = ('+', '-', '*', '/', '%', '?', ':', ',', '.', '(', '[', '=', '<', '>')


def _strip_comment(s: str) -> str:
    """Drop a trailing // comment, preserving string literals (# color literals are kept)."""
    instr = None
    i, n = 0, len(s)
    while i < n:
        c = s[i]
        if instr:
            if c == '\\' and i + 1 < n:
                i += 2; continue
            if c == instr:
                instr = None
            i += 1; continue
        if c in ('"', "'"):
            instr = c; i += 1; continue
        if c == '/' and i + 1 < n and s[i + 1] == '/':
            return s[:i]
        i += 1
    return s


def _net_depth(s: str) -> int:
    """Net unclosed ( and [ on a line, ignoring strings and comments."""
    instr = None
    d = 0
    i, n = 0, len(s)
    while i < n:
        c = s[i]
        if instr:
            if c == '\\' and i + 1 < n:
                i += 2; continue
            if c == instr:
                instr = None
            i += 1; continue
        if c in ('"', "'"):
            instr = c; i += 1; continue
        if c == '/' and i + 1 < n and s[i + 1] == '/':
            break
        if c in '([':
            d += 1
        elif c in ')]':
            d -= 1
        i += 1
    return d


def _starts_cont(stripped: str) -> bool:
    """A statement never STARTS with a binary operator -> such a line continues the previous."""
    if stripped.startswith('and ') or stripped.startswith('or ') or stripped in ('and', 'or'):
        return True
    return stripped.startswith(_CONT_START)


def _ends_cont(code: str) -> bool:
    """A line ending in a binary operator / open bracket continues onto the next."""
    code = code.rstrip()
    if code.endswith(' and') or code.endswith(' or') or code.endswith('=>'):
        return True
    return code.endswith(_CONT_END)


def _logical_lines(source: str):
    """Merge physical lines into logical lines (Pine v5 line-continuation).
    Continues when: inside unclosed ()/[]; next line starts with a binary operator; or the
    current line ends with one. Blank/comment lines at depth 0 end a logical line. The first
    physical line's indentation is preserved so INDENT/DEDENT handling is unchanged.
    Yields (line_num, text)."""
    raw = source.split('\n')
    n = len(raw)
    out = []
    i = 0
    while i < n:
        line = raw[i]
        stripped = line.strip()
        if stripped == '' or (stripped.startswith('//') and not stripped.startswith('//@')):
            i += 1
            continue
        if stripped.startswith('//@'):
            out.append((i + 1, line))   # pragma stays standalone
            i += 1
            continue
        start = i + 1
        merged = _strip_comment(line).rstrip()
        depth = _net_depth(line)
        j = i + 1
        while j < n:
            nxt = raw[j]
            nst = nxt.strip()
            if depth > 0:
                if nst != '' and not nst.startswith('//'):
                    merged = merged.rstrip() + ' ' + _strip_comment(nxt).strip()
                depth += _net_depth(nxt)
                j += 1
                continue
            if nst == '' or nst.startswith('//'):
                break
            if _starts_cont(nst) or _ends_cont(_strip_comment(merged)):
                merged = merged.rstrip() + ' ' + _strip_comment(nxt).strip()
                depth += _net_depth(nxt)
                j += 1
                continue
            break
        out.append((start, merged))
        i = j
    return out


def tokenize(source: str) -> List[Token]:
    """Tokenize Pine Script v5 source code into a token stream.

    Returns a list of tokens including INDENT/DEDENT for block structure.
    """
    tokens: List[Token] = []
    indent_stack = [0]  # Track indentation levels

    # Merge physical lines into logical lines first so Pine v5 multi-line expressions don't
    # emit a spurious NEWLINE that the parser rejects. First-line indentation is preserved. (2026-06-29)
    for line_num, raw_line in _logical_lines(source):
        # _logical_lines never yields blank lines; pure comments are dropped.
        # Handle //@version pragma.
        stripped = raw_line.lstrip()
        if stripped.startswith('//@'):
            tokens.append(Token(TokenType.PRAGMA, stripped, line_num, 0))
            continue
        if stripped.startswith('//'):
            continue  # Pure comment line, skip

        # Calculate indentation (spaces only — Pine uses 4-space indent)
        indent = 0
        for ch in raw_line:
            if ch == ' ':
                indent += 1
            elif ch == '\t':
                indent += 4  # Treat tab as 4 spaces
            else:
                break

        # Emit INDENT/DEDENT tokens based on indentation change
        if indent > indent_stack[-1]:
            indent_stack.append(indent)
            tokens.append(Token(TokenType.INDENT, '', line_num, 0))
        else:
            while indent < indent_stack[-1]:
                indent_stack.pop()
                tokens.append(Token(TokenType.DEDENT, '', line_num, 0))

        # Tokenize the line content (after stripping leading whitespace)
        line_content = raw_line.lstrip()
        pos = 0

        while pos < len(line_content):
            ch = line_content[pos]

            # Skip inline whitespace
            if ch in ' \t':
                pos += 1
                continue

            # Inline comment
            if ch == '/' and pos + 1 < len(line_content) and line_content[pos + 1] == '/':
                break  # Rest of line is comment

            col = indent + pos

            # String literals
            if ch in ('"', "'"):
                quote = ch
                start = pos
                pos += 1
                while pos < len(line_content) and line_content[pos] != quote:
                    if line_content[pos] == '\\':
                        pos += 1  # Skip escape
                    pos += 1
                pos += 1  # closing quote
                tokens.append(Token(TokenType.STRING, line_content[start + 1:pos - 1], line_num, col))
                continue

            # Numbers
            if ch.isdigit() or (ch == '.' and pos + 1 < len(line_content) and line_content[pos + 1].isdigit()):
                start = pos
                has_dot = False
                while pos < len(line_content) and (line_content[pos].isdigit() or line_content[pos] == '.'):
                    if line_content[pos] == '.':
                        if has_dot:
                            break  # Second dot — stop
                        has_dot = True
                    pos += 1
                num_str = line_content[start:pos]
                if has_dot:
                    tokens.append(Token(TokenType.FLOAT, num_str, line_num, col))
                else:
                    tokens.append(Token(TokenType.INTEGER, num_str, line_num, col))
                continue

            # Identifiers and keywords
            if ch.isalpha() or ch == '_':
                start = pos
                while pos < len(line_content) and (line_content[pos].isalnum() or line_content[pos] == '_'):
                    pos += 1
                word = line_content[start:pos]
                tt = KEYWORDS.get(word, TokenType.IDENTIFIER)
                tokens.append(Token(tt, word, line_num, col))
                continue

            # Multi-character operators
            if ch == ':' and pos + 1 < len(line_content) and line_content[pos + 1] == '=':
                tokens.append(Token(TokenType.REASSIGN, ':=', line_num, col))
                pos += 2
                continue
            if ch == '=' and pos + 1 < len(line_content) and line_content[pos + 1] == '=':
                tokens.append(Token(TokenType.EQ, '==', line_num, col))
                pos += 2
                continue
            if ch == '=' and pos + 1 < len(line_content) and line_content[pos + 1] == '>':
                tokens.append(Token(TokenType.ARROW, '=>', line_num, col))
                pos += 2
                continue
            if ch == '!' and pos + 1 < len(line_content) and line_content[pos + 1] == '=':
                tokens.append(Token(TokenType.NEQ, '!=', line_num, col))
                pos += 2
                continue
            if ch == '<' and pos + 1 < len(line_content) and line_content[pos + 1] == '=':
                tokens.append(Token(TokenType.LTE, '<=', line_num, col))
                pos += 2
                continue
            if ch == '>' and pos + 1 < len(line_content) and line_content[pos + 1] == '=':
                tokens.append(Token(TokenType.GTE, '>=', line_num, col))
                pos += 2
                continue

            # Single-character operators
            SINGLE_OPS = {
                '=': TokenType.ASSIGN,
                '+': TokenType.PLUS,
                '-': TokenType.MINUS,
                '*': TokenType.STAR,
                '/': TokenType.SLASH,
                '%': TokenType.PERCENT,
                '<': TokenType.LT,
                '>': TokenType.GT,
                '?': TokenType.QUESTION,
                ':': TokenType.COLON,
                '.': TokenType.DOT,
                ',': TokenType.COMMA,
                '[': TokenType.LBRACKET,
                ']': TokenType.RBRACKET,
                '(': TokenType.LPAREN,
                ')': TokenType.RPAREN,
            }
            if ch in SINGLE_OPS:
                tokens.append(Token(SINGLE_OPS[ch], ch, line_num, col))
                pos += 1
                continue

            # Hash (for color literals like #e91e63)
            if ch == '#':
                start = pos
                pos += 1
                while pos < len(line_content) and (line_content[pos].isalnum()):
                    pos += 1
                tokens.append(Token(TokenType.STRING, line_content[start:pos], line_num, col))
                continue

            # Unknown character — skip
            pos += 1

        # Emit NEWLINE at end of each meaningful line
        tokens.append(Token(TokenType.NEWLINE, '\\n', line_num, 0))

    # Emit remaining DEDENTs at EOF
    while len(indent_stack) > 1:
        indent_stack.pop()
        tokens.append(Token(TokenType.DEDENT, '', line_num, 0))

    tokens.append(Token(TokenType.EOF, '', line_num, 0))
    return tokens
