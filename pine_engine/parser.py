"""Pine Script v5 Parser — recursive descent parser producing AST from tokens.

Handles:
  - Top-level statements: strategy/indicator declarations, var/varip, assignments,
    if/else, for/to, function definitions, expression statements
  - Expressions: binary ops with precedence, unary, ternary, history [N],
    function calls with positional + named args, member access
  - Indentation-based blocks (INDENT/DEDENT)
"""

from __future__ import annotations
from typing import List, Optional, Dict, Tuple

from pine_engine.lexer import Token, TokenType
from pine_engine.ast_nodes import *


class ParseError(Exception):
    def __init__(self, message: str, token: Optional[Token] = None):
        self.token = token
        loc = f" at line {token.line}" if token else ""
        super().__init__(f"{message}{loc}")


class Parser:
    def __init__(self, tokens: List[Token]):
        self.tokens = tokens
        self.pos = 0
        self.inputs: Dict[str, dict] = {}  # Extracted input.* declarations

    # ── Token navigation ──

    def current(self) -> Token:
        if self.pos < len(self.tokens):
            return self.tokens[self.pos]
        return Token(TokenType.EOF, '', 0, 0)

    def peek(self, offset: int = 0) -> Token:
        idx = self.pos + offset
        if idx < len(self.tokens):
            return self.tokens[idx]
        return Token(TokenType.EOF, '', 0, 0)

    def advance(self) -> Token:
        tok = self.current()
        self.pos += 1
        return tok

    def expect(self, tt: TokenType) -> Token:
        tok = self.current()
        if tok.type != tt:
            raise ParseError(f"Expected {tt.name}, got {tok.type.name} ({tok.value!r})", tok)
        return self.advance()

    def match(self, *types: TokenType) -> Optional[Token]:
        if self.current().type in types:
            return self.advance()
        return None

    def skip_newlines(self):
        while self.current().type == TokenType.NEWLINE:
            self.advance()

    def at_end(self) -> bool:
        return self.current().type == TokenType.EOF

    # ── Top-level parsing ──

    def parse(self) -> Program:
        """Parse a complete Pine Script program."""
        self.skip_newlines()
        pragma = None

        # Check for pragma
        if self.current().type == TokenType.PRAGMA:
            pragma = self.advance().value
            self.skip_newlines()

        statements = []
        while not self.at_end():
            self.skip_newlines()
            if self.at_end():
                break
            stmt = self.parse_statement()
            if stmt is not None:
                statements.append(stmt)
            self.skip_newlines()

        return Program(statements=statements, pragma=pragma)

    def parse_statement(self) -> Optional[Statement]:
        """Parse a single statement."""
        tok = self.current()

        # Strategy/indicator declaration
        if tok.type == TokenType.STRATEGY:
            return self.parse_strategy_or_indicator_decl('strategy')
        if tok.type == TokenType.INDICATOR:
            return self.parse_strategy_or_indicator_decl('indicator')

        # var/varip declaration
        if tok.type in (TokenType.VAR, TokenType.VARIP):
            return self.parse_var_declaration()

        # if statement
        if tok.type == TokenType.IF:
            return self.parse_if_statement()

        # for statement
        if tok.type == TokenType.FOR:
            return self.parse_for_statement()

        # break
        if tok.type == TokenType.BREAK:
            self.advance()
            self.match(TokenType.NEWLINE)
            return BreakStatement()

        # Assignment (name := expr) or declaration (name = expr) or expression
        if tok.type in (TokenType.IDENTIFIER, TokenType.TYPE_INT, TokenType.TYPE_FLOAT,
                        TokenType.TYPE_BOOL, TokenType.TYPE_STRING):
            return self.parse_assignment_or_expr()

        # DEDENT/INDENT at top level — consume and return None
        if tok.type in (TokenType.DEDENT, TokenType.INDENT):
            self.advance()
            return None

        # Fallback: try expression statement
        expr = self.parse_expression()
        self.match(TokenType.NEWLINE)
        return ExprStatement(expr=expr)

    def parse_strategy_or_indicator_decl(self, kind: str):
        """Parse strategy("name", ...) or indicator("name", ...)."""
        self.advance()  # strategy/indicator keyword
        if self.current().type == TokenType.DOT:
            # strategy.order etc. — this is a function call, not a declaration
            self.pos -= 1
            return self.parse_assignment_or_expr()

        self.expect(TokenType.LPAREN)
        self.skip_newlines()
        name = ""
        if self.current().type == TokenType.STRING:
            name = self.advance().value

        kwargs = {}
        while True:
            # Skip whitespace tokens inside parens
            while self.current().type in (TokenType.NEWLINE, TokenType.INDENT, TokenType.DEDENT):
                self.advance()
            if self.current().type == TokenType.RPAREN or self.at_end():
                break
            if self.current().type == TokenType.COMMA:
                self.advance()
                continue
            # Parse named argument
            if (self.current().type == TokenType.IDENTIFIER and
                    self.peek(1).type == TokenType.ASSIGN):
                key = self.advance().value
                self.expect(TokenType.ASSIGN)
                val = self.parse_expression()
                kwargs[key] = self._expr_to_value(val)
            else:
                # Positional — skip
                self.parse_expression()

        self.expect(TokenType.RPAREN)
        self.match(TokenType.NEWLINE)

        if kind == 'strategy':
            return StrategyDeclaration(name=name, kwargs=kwargs)
        return IndicatorDeclaration(name=name, kwargs=kwargs)

    def parse_var_declaration(self):
        """Parse var [type] name = expr or varip [type] name = expr."""
        is_var = self.current().type == TokenType.VAR
        is_varip = self.current().type == TokenType.VARIP
        self.advance()  # var/varip

        # Optional type hint (may include [] for array types: int[], float[], etc.)
        type_hint = None
        if self.current().type in (TokenType.TYPE_INT, TokenType.TYPE_FLOAT,
                                   TokenType.TYPE_BOOL, TokenType.TYPE_STRING,
                                   TokenType.TYPE_COLOR):
            type_hint = self.advance().value
            # Handle array type: int[], float[], etc.
            if self.current().type == TokenType.LBRACKET:
                self.advance()  # [
                self.expect(TokenType.RBRACKET)  # ]
                type_hint += '[]'
        # Also handle line[] label[] box[] — these are identifier types
        elif self.current().type == TokenType.IDENTIFIER:
            # Check if it looks like a type: line[], label[], box[]
            if self.peek(1).type == TokenType.LBRACKET and self.peek(2).type == TokenType.RBRACKET:
                type_hint = self.advance().value  # line/label/box
                self.advance()  # [
                self.advance()  # ]
                type_hint += '[]'

        # Variable name
        name = self.expect(TokenType.IDENTIFIER).value

        # = initializer
        self.expect(TokenType.ASSIGN)
        initializer = self.parse_expression()
        self.match(TokenType.NEWLINE)

        return VarDeclaration(name=name, initializer=initializer,
                              is_var=is_var, is_varip=is_varip,
                              type_hint=type_hint)

    def parse_assignment_or_expr(self):
        """Parse: name = expr (declaration), name := expr (assignment),
        name(params) => body (function def), or expression statement."""

        # Check for type hint before identifier: int pivotLeft = ...
        type_hint = None
        if self.current().type in (TokenType.TYPE_INT, TokenType.TYPE_FLOAT,
                                   TokenType.TYPE_BOOL, TokenType.TYPE_STRING):
            # Could be type hint: float x = ... or just identifier
            if self.peek(1).type == TokenType.IDENTIFIER:
                type_hint = self.advance().value

        # Save position for backtracking
        start_pos = self.pos

        # Try to parse identifier (could be dotted)
        if self.current().type == TokenType.IDENTIFIER:
            name = self.advance().value

            # Function definition: name(params) =>
            # Look ahead to check if this is a func def before treating as call
            if self.current().type == TokenType.LPAREN:
                # Scan ahead for => after matching parens
                saved = self.pos
                depth = 0
                is_func_def = False
                scan = self.pos
                while scan < len(self.tokens):
                    tt = self.tokens[scan].type
                    if tt == TokenType.LPAREN:
                        depth += 1
                    elif tt == TokenType.RPAREN:
                        depth -= 1
                        if depth == 0:
                            # Check what follows the closing paren
                            nxt = scan + 1
                            while nxt < len(self.tokens) and self.tokens[nxt].type in (TokenType.NEWLINE, TokenType.INDENT, TokenType.DEDENT):
                                nxt += 1
                            if nxt < len(self.tokens) and self.tokens[nxt].type == TokenType.ARROW:
                                is_func_def = True
                            break
                    elif tt == TokenType.EOF:
                        break
                    scan += 1

                if is_func_def:
                    self.advance()  # (
                    params = []
                    while self.current().type != TokenType.RPAREN:
                        if self.current().type in (TokenType.COMMA, TokenType.NEWLINE, TokenType.INDENT, TokenType.DEDENT):
                            self.advance()
                            continue
                        if self.current().type == TokenType.IDENTIFIER:
                            params.append(self.advance().value)
                        else:
                            break
                    self.expect(TokenType.RPAREN)
                    # Skip to =>
                    while self.current().type in (TokenType.NEWLINE, TokenType.INDENT, TokenType.DEDENT):
                        self.advance()
                    self.expect(TokenType.ARROW)
                    self.skip_newlines()
                    if self.current().type == TokenType.INDENT:
                        body = self.parse_block()
                    else:
                        body = self.parse_expression()
                    self.match(TokenType.NEWLINE)
                    return FunctionDef(name=name, params=params, body=body)

            # Reassignment: name := expr
            if self.current().type == TokenType.REASSIGN:
                self.advance()
                value = self.parse_expression()
                self.match(TokenType.NEWLINE)
                return Assignment(target=name, value=value)

            # Declaration: name = expr (or type name = expr)
            if self.current().type == TokenType.ASSIGN:
                self.advance()
                initializer = self.parse_expression()
                self.match(TokenType.NEWLINE)

                # Check if this is an input.* call — extract to inputs dict
                if isinstance(initializer, FunctionCall) and initializer.name.startswith('input.'):
                    self._extract_input(name, initializer)

                return VarDeclaration(name=name, initializer=initializer,
                                      type_hint=type_hint)

        # Not an assignment — backtrack and parse as expression
        self.pos = start_pos
        if type_hint:
            self.pos -= 1  # Back past the type hint
        expr = self.parse_expression()
        self.match(TokenType.NEWLINE)
        return ExprStatement(expr=expr)

    def parse_if_statement(self):
        """Parse if/else if/else with indented blocks."""
        self.expect(TokenType.IF)
        condition = self.parse_expression()
        self.match(TokenType.NEWLINE)
        then_body = self.parse_block()

        elif_branches = []
        else_body = None

        while True:
            self.skip_newlines()
            if self.current().type == TokenType.ELSE:
                self.advance()
                if self.current().type == TokenType.IF:
                    # else if
                    self.advance()
                    elif_cond = self.parse_expression()
                    self.match(TokenType.NEWLINE)
                    elif_body = self.parse_block()
                    elif_branches.append((elif_cond, elif_body))
                else:
                    # else
                    self.match(TokenType.NEWLINE)
                    else_body = self.parse_block()
                    break
            else:
                break

        return IfStatement(condition=condition, then_body=then_body,
                           elif_branches=elif_branches, else_body=else_body)

    def parse_for_statement(self):
        """Parse for var_name = start to end ... body"""
        self.expect(TokenType.FOR)
        var_name = self.expect(TokenType.IDENTIFIER).value
        self.expect(TokenType.ASSIGN)
        start = self.parse_expression()
        self.expect(TokenType.TO)
        end = self.parse_expression()
        self.match(TokenType.NEWLINE)
        body = self.parse_block()
        return ForStatement(var_name=var_name, start=start, end=end, body=body)

    def parse_block(self) -> List[Statement]:
        """Parse an indented block of statements."""
        self.skip_newlines()
        if self.current().type != TokenType.INDENT:
            # Single statement on same line (shouldn't happen in Pine but handle gracefully)
            stmt = self.parse_statement()
            return [stmt] if stmt else []

        self.expect(TokenType.INDENT)
        stmts = []
        while self.current().type != TokenType.DEDENT and not self.at_end():
            self.skip_newlines()
            if self.current().type == TokenType.DEDENT:
                break
            stmt = self.parse_statement()
            if stmt is not None:
                stmts.append(stmt)
            self.skip_newlines()

        self.match(TokenType.DEDENT)
        return stmts

    # ── Expression parsing (precedence climbing) ──

    def parse_expression(self) -> Expr:
        """Entry point for expression parsing — handles ternary."""
        return self.parse_ternary()

    def parse_ternary(self) -> Expr:
        """condition ? true_expr : false_expr
        Handles multi-line ternaries where ? and : can be followed by newlines.
        """
        expr = self.parse_or()
        if self.current().type == TokenType.QUESTION:
            self.advance()
            # Skip newlines/indent after ? (multi-line ternary)
            while self.current().type in (TokenType.NEWLINE, TokenType.INDENT, TokenType.DEDENT):
                self.advance()
            true_expr = self.parse_expression()
            # Skip newlines/indent before :
            while self.current().type in (TokenType.NEWLINE, TokenType.INDENT, TokenType.DEDENT):
                self.advance()
            self.expect(TokenType.COLON)
            # Skip newlines/indent after :
            while self.current().type in (TokenType.NEWLINE, TokenType.INDENT, TokenType.DEDENT):
                self.advance()
            false_expr = self.parse_expression()
            return Ternary(condition=expr, true_expr=true_expr, false_expr=false_expr)
        return expr

    def _skip_continuation(self):
        """Skip newlines/indent/dedent after binary operators (line continuation)."""
        while self.current().type in (TokenType.NEWLINE, TokenType.INDENT, TokenType.DEDENT):
            self.advance()

    def parse_or(self) -> Expr:
        left = self.parse_and()
        while self.current().type == TokenType.OR:
            self.advance()
            self._skip_continuation()
            right = self.parse_and()
            left = BinaryOp(left=left, op='or', right=right)
        return left

    def parse_and(self) -> Expr:
        left = self.parse_equality()
        while self.current().type == TokenType.AND:
            self.advance()
            self._skip_continuation()
            right = self.parse_equality()
            left = BinaryOp(left=left, op='and', right=right)
        return left

    def parse_equality(self) -> Expr:
        left = self.parse_comparison()
        while self.current().type in (TokenType.EQ, TokenType.NEQ):
            op = self.advance().value
            right = self.parse_comparison()
            left = BinaryOp(left=left, op=op, right=right)
        return left

    def parse_comparison(self) -> Expr:
        left = self.parse_addition()
        while self.current().type in (TokenType.LT, TokenType.GT, TokenType.LTE, TokenType.GTE):
            op = self.advance().value
            right = self.parse_addition()
            left = BinaryOp(left=left, op=op, right=right)
        return left

    def parse_addition(self) -> Expr:
        left = self.parse_multiplication()
        while self.current().type in (TokenType.PLUS, TokenType.MINUS):
            op = self.advance().value
            right = self.parse_multiplication()
            left = BinaryOp(left=left, op=op, right=right)
        return left

    def parse_multiplication(self) -> Expr:
        left = self.parse_unary()
        while self.current().type in (TokenType.STAR, TokenType.SLASH, TokenType.PERCENT):
            op = self.advance().value
            right = self.parse_unary()
            left = BinaryOp(left=left, op=op, right=right)
        return left

    def parse_unary(self) -> Expr:
        if self.current().type == TokenType.MINUS:
            self.advance()
            operand = self.parse_unary()
            return UnaryOp(op='-', operand=operand)
        if self.current().type == TokenType.NOT:
            self.advance()
            operand = self.parse_unary()
            return UnaryOp(op='not', operand=operand)
        return self.parse_postfix()

    def parse_postfix(self) -> Expr:
        """Parse postfix operations: [N] history, .member, (args) call."""
        expr = self.parse_primary()

        while True:
            # History reference: expr[offset]
            if self.current().type == TokenType.LBRACKET:
                self.advance()
                offset = self.parse_expression()
                self.expect(TokenType.RBRACKET)
                expr = HistoryRef(series=expr, offset=offset)

            # Member access or method call: expr.name or expr.name(args)
            elif self.current().type == TokenType.DOT:
                self.advance()
                member = self.current().value
                self.advance()  # member name

                # Check if it's a method call: expr.name(args)
                if self.current().type == TokenType.LPAREN:
                    # Build dotted name for function call
                    dotted = self._build_dotted_name(expr, member)
                    args, kwargs = self.parse_call_args()
                    expr = FunctionCall(name=dotted, args=args, kwargs=kwargs)
                else:
                    # Just member access (e.g., strategy.long, dayofweek.monday)
                    dotted = self._build_dotted_name(expr, member)
                    expr = Identifier(name=dotted)

            # Direct function call on identifier: name(args)
            elif self.current().type == TokenType.LPAREN and isinstance(expr, Identifier):
                args, kwargs = self.parse_call_args()
                expr = FunctionCall(name=expr.name, args=args, kwargs=kwargs)

            else:
                break

        return expr

    def parse_primary(self) -> Expr:
        """Parse primary expressions: literals, identifiers, grouped (parens), arrays."""
        tok = self.current()

        # Array literal: [elem1, elem2, ...]
        if tok.type == TokenType.LBRACKET:
            self.advance()
            elements = []
            while self.current().type != TokenType.RBRACKET and not self.at_end():
                if self.current().type == TokenType.COMMA:
                    self.advance()
                    continue
                elements.append(self.parse_expression())
            self.expect(TokenType.RBRACKET)
            # Represent as a function call to a pseudo-function
            return FunctionCall(name='__array__', args=elements)

        # Parenthesized expression
        if tok.type == TokenType.LPAREN:
            self.advance()
            expr = self.parse_expression()
            self.expect(TokenType.RPAREN)
            return expr

        # Number literals
        if tok.type == TokenType.INTEGER:
            self.advance()
            return NumberLiteral(value=int(tok.value))
        if tok.type == TokenType.FLOAT:
            self.advance()
            return NumberLiteral(value=float(tok.value))

        # String literal
        if tok.type == TokenType.STRING:
            self.advance()
            return StringLiteral(value=tok.value)

        # Boolean literals
        if tok.type == TokenType.BOOL_TRUE:
            self.advance()
            return BoolLiteral(value=True)
        if tok.type == TokenType.BOOL_FALSE:
            self.advance()
            return BoolLiteral(value=False)

        # na — could be literal `na` or function call `na(expr)`
        if tok.type == TokenType.NA:
            self.advance()
            if self.current().type == TokenType.LPAREN:
                # na(x) is a function call, not a literal
                args, kwargs = self.parse_call_args()
                return FunctionCall(name='na', args=args, kwargs=kwargs)
            return NaLiteral()

        # Identifiers (including strategy, indicator as identifiers in expressions)
        if tok.type in (TokenType.IDENTIFIER, TokenType.STRATEGY, TokenType.INDICATOR):
            self.advance()
            return Identifier(name=tok.value)

        # Type keywords used as identifiers (e.g., in type declarations)
        if tok.type in (TokenType.TYPE_INT, TokenType.TYPE_FLOAT, TokenType.TYPE_BOOL,
                        TokenType.TYPE_STRING, TokenType.TYPE_COLOR):
            self.advance()
            return Identifier(name=tok.value)

        raise ParseError(f"Unexpected token: {tok.type.name} ({tok.value!r})", tok)

    def parse_call_args(self) -> Tuple[List[Expr], Dict[str, Expr]]:
        """Parse function call arguments: (pos_args, key=value, ...).
        Handles multi-line argument lists by skipping NEWLINEs and INDENT/DEDENT inside parens.
        """
        self.expect(TokenType.LPAREN)
        args = []
        kwargs = {}

        while self.current().type != TokenType.RPAREN and not self.at_end():
            # Skip newlines and indentation inside parens (multi-line calls)
            if self.current().type in (TokenType.NEWLINE, TokenType.INDENT, TokenType.DEDENT):
                self.advance()
                continue
            if self.current().type == TokenType.COMMA:
                self.advance()
                continue

            # Check for named argument: key = value
            # key can be IDENTIFIER or type keywords (color=, string=, etc.)
            is_named = False
            if self.peek(1).type == TokenType.ASSIGN:
                if self.current().type in (TokenType.IDENTIFIER, TokenType.TYPE_INT,
                                           TokenType.TYPE_FLOAT, TokenType.TYPE_BOOL,
                                           TokenType.TYPE_STRING, TokenType.TYPE_COLOR):
                    is_named = True
            if is_named:
                key = self.advance().value
                self.expect(TokenType.ASSIGN)
                val = self.parse_expression()
                kwargs[key] = val
            else:
                args.append(self.parse_expression())

        self.expect(TokenType.RPAREN)
        return args, kwargs

    # ── Helpers ──

    def _build_dotted_name(self, expr: Expr, member: str) -> str:
        """Build dotted name string from expression chain."""
        if isinstance(expr, Identifier):
            return f"{expr.name}.{member}"
        if isinstance(expr, FunctionCall):
            return f"{expr.name}.{member}"
        return f"?.{member}"

    def _expr_to_value(self, expr: Expr):
        """Convert simple expressions to Python values (for declaration kwargs)."""
        if isinstance(expr, NumberLiteral):
            return expr.value
        if isinstance(expr, StringLiteral):
            return expr.value
        if isinstance(expr, BoolLiteral):
            return expr.value
        if isinstance(expr, NaLiteral):
            return None
        if isinstance(expr, Identifier):
            return expr.name
        if isinstance(expr, UnaryOp) and expr.op == '-' and isinstance(expr.operand, NumberLiteral):
            return -expr.operand.value
        return None

    def _extract_input(self, name: str, call: FunctionCall):
        """Extract input.* call into the inputs dictionary."""
        info = {'type': call.name.split('.')[-1]}  # int, float, bool, string, color

        # First positional arg is the default value
        if call.args:
            info['default'] = self._expr_to_value(call.args[0])

        # Named args
        for k, v in call.kwargs.items():
            info[k] = self._expr_to_value(v)

        self.inputs[name] = info


def parse(tokens: List[Token]) -> Tuple[Program, Dict]:
    """Parse tokens into AST and extract input declarations.

    Returns:
        (program_ast, inputs_dict)
    """
    parser = Parser(tokens)
    program = parser.parse()
    return program, parser.inputs
