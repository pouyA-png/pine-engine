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


def tokenize(source: str) -> List[Token]:
    """Tokenize Pine Script v5 source code into a token stream.

    Returns a list of tokens including INDENT/DEDENT for block structure.
    """
    tokens: List[Token] = []
    lines = source.split('\n')
    indent_stack = [0]  # Track indentation levels
    line_num = 0

    for raw_line in lines:
        line_num += 1

        # Skip completely empty lines
        if raw_line.strip() == '':
            continue

        # Handle comments: // to end of line
        # But preserve //@version pragma
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
