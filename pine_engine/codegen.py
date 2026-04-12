"""Pine Script v5 → Python Code Generator (Transpiler).

Walks the AST and emits executable Python source code that:
  - Uses Series objects for variables referenced with [N] history
  - Uses ctx.var_* for persistent `var` variables
  - Calls into runtime builtins (ta.pivothigh → ctx.builtins.ta_pivothigh)
  - Calls into strategy API (strategy.order → ctx.strategy.order)
  - Skips all visualization code (line.new, label.new, box.new, plotshape, etc.)

The generated code consists of two functions:
  - initialize(ctx): set up var declarations (run once on bar 0)
  - execute_bar(ctx): run the Pine logic for one bar
"""

from __future__ import annotations
from typing import Set, Dict, List, Optional
from pine_engine.ast_nodes import *  # noqa: includes WhileStatement

# Functions/namespaces that are visualization-only → skip entirely
SKIP_FUNCTIONS = {
    'line.new', 'line.delete', 'line.set_x1', 'line.set_x2',
    'label.new', 'label.delete',
    'box.new', 'box.delete',
    'plotshape', 'plotchar', 'plotarrow', 'plotbar', 'plotcandle', 'plot',
    'alertcondition', 'alert',
    'color.new', 'color.rgb',
    # Array functions (only used for viz state in this bot)
    'array.new_int', 'array.new_line', 'array.new_label', 'array.new_box',
    'array.new_float', 'array.new_string', 'array.new_bool',
    'array.size', 'array.push', 'array.shift', 'array.get',
    'array.clear', 'array.indexof', 'array.set',
}

# Functions that map to runtime builtins
BUILTIN_MAP = {
    'hour': 'pine_hour',
    'minute': 'pine_minute',
    'dayofweek': 'pine_dayofweek',
    'year': 'pine_year',
    'month': 'pine_month',
    'dayofmonth': 'pine_dayofmonth',
    'ta.pivothigh': 'ta_pivothigh',
    'ta.pivotlow': 'ta_pivotlow',
    'ta.highest': 'ta_highest',
    'ta.lowest': 'ta_lowest',
    'ta.rsi': 'ta_rsi',
    'ta.crossover': 'ta_crossover',
    'ta.crossunder': 'ta_crossunder',
    'math.abs': 'pine_abs',
    'math.min': 'pine_min',
    'math.max': 'pine_max',
    'math.round': 'pine_round',
    'math.floor': 'pine_floor',
    'na': 'is_na',
    'str.tostring': 'str',
}

# Pine constants → Python values
CONSTANT_MAP = {
    'strategy.long': 'STRATEGY_LONG',
    'strategy.short': 'STRATEGY_SHORT',
    'strategy.fixed': '"fixed"',
    'dayofweek.sunday': '1',
    'dayofweek.monday': '2',
    'dayofweek.tuesday': '3',
    'dayofweek.wednesday': '4',
    'dayofweek.thursday': '5',
    'dayofweek.friday': '6',
    'dayofweek.saturday': '7',
    'extend.none': '"none"',
    'line.style_dashed': '"dashed"',
    'line.style_dotted': '"dotted"',
    'label.style_label_left': '"label_left"',
    'label.style_label_down': '"label_down"',
    'label.style_label_up': '"label_up"',
    'size.small': '"small"',
    'size.tiny': '"tiny"',
    'shape.triangledown': '"triangledown"',
    'shape.triangleup': '"triangleup"',
    'shape.xcross': '"xcross"',
    'location.abovebar': '"abovebar"',
    'location.belowbar': '"belowbar"',
}

# Pine operator → Python operator/function
OP_MAP = {
    '+': '+', '-': '-', '*': '*', '/': '/', '%': '%',
    '==': '==', '!=': '!=', '<': '<', '>': '>', '<=': '<=', '>=': '>=',
}

# Built-in series variable names (provided by runtime context)
BUILTIN_SERIES = {'time', 'open', 'high', 'low', 'close', 'bar_index'}

# Variables that need Series treatment (referenced with [N])
# Will be detected via static analysis
SERIES_VARS: Set[str] = set()


class CodeGenerator:
    """Generates Python source code from Pine Script AST."""

    def __init__(self, program: Program, inputs: Dict):
        self.program = program
        self.inputs = inputs
        self.var_names: Set[str] = set()          # All `var` declared names
        self.all_declared: Set[str] = set()        # All declared variable names
        self.series_vars: Set[str] = set()         # Vars that need Series (used with [N])
        self.skip_vars: Set[str] = set()           # Vars assigned from skip functions
        self.indent_level = 0
        self.strategy_settings: Dict = {}

        # First pass: collect var names and detect series usage
        self._analyze()

    def _analyze(self):
        """Static analysis: find var declarations, series usage, skip targets."""
        for stmt in self.program.statements:
            self._analyze_stmt(stmt)

    def _analyze_stmt(self, stmt):
        if isinstance(stmt, StrategyDeclaration):
            self.strategy_settings = stmt.kwargs
        elif isinstance(stmt, VarDeclaration):
            self.all_declared.add(stmt.name)
            if stmt.is_var or stmt.is_varip:
                self.var_names.add(stmt.name)
            # Check if initializer is a skip function
            if isinstance(stmt.initializer, FunctionCall) and self._is_skip_func(stmt.initializer.name):
                self.skip_vars.add(stmt.name)
            self._analyze_expr_for_series(stmt.initializer)
        elif isinstance(stmt, Assignment):
            self._analyze_expr_for_series(stmt.value)
        elif isinstance(stmt, IfStatement):
            self._analyze_expr_for_series(stmt.condition)
            for s in stmt.then_body:
                self._analyze_stmt(s)
            for cond, body in stmt.elif_branches:
                self._analyze_expr_for_series(cond)
                for s in body:
                    self._analyze_stmt(s)
            if stmt.else_body:
                for s in stmt.else_body:
                    self._analyze_stmt(s)
        elif isinstance(stmt, ForStatement):
            self._analyze_expr_for_series(stmt.start)
            self._analyze_expr_for_series(stmt.end)
            for s in stmt.body:
                self._analyze_stmt(s)
        elif isinstance(stmt, ExprStatement):
            self._analyze_expr_for_series(stmt.expr)

    def _analyze_expr_for_series(self, expr):
        """Find all variables used with [N] history operator."""
        if expr is None:
            return
        if isinstance(expr, HistoryRef):
            if isinstance(expr.series, Identifier):
                self.series_vars.add(expr.series.name)
            self._analyze_expr_for_series(expr.series)
            self._analyze_expr_for_series(expr.offset)
        elif isinstance(expr, BinaryOp):
            self._analyze_expr_for_series(expr.left)
            self._analyze_expr_for_series(expr.right)
        elif isinstance(expr, UnaryOp):
            self._analyze_expr_for_series(expr.operand)
        elif isinstance(expr, Ternary):
            self._analyze_expr_for_series(expr.condition)
            self._analyze_expr_for_series(expr.true_expr)
            self._analyze_expr_for_series(expr.false_expr)
        elif isinstance(expr, FunctionCall):
            for a in expr.args:
                self._analyze_expr_for_series(a)
            for v in expr.kwargs.values():
                self._analyze_expr_for_series(v)

    def _is_skip_func(self, name: str) -> bool:
        """Check if a function should be skipped (visualization only)."""
        if name in SKIP_FUNCTIONS:
            return True
        # Any function starting with these prefixes
        for prefix in ('line.', 'label.', 'box.', 'array.', 'color.'):
            if name.startswith(prefix):
                return True
        return False

    # ── Code generation ──

    def generate(self) -> str:
        """Generate complete Python module source."""
        lines = []
        lines.append('"""Auto-generated Python from Pine Script. Do not edit manually."""')
        lines.append('')
        lines.append('from pine_engine.runtime.na import (')
        lines.append('    NA, is_na, pine_add, pine_sub, pine_mul, pine_div,')
        lines.append('    pine_eq, pine_neq, pine_lt, pine_gt, pine_lte, pine_gte,')
        lines.append('    pine_and, pine_or, pine_not,')
        lines.append('    pine_abs, pine_min, pine_max, pine_round, pine_floor')
        lines.append(')')
        lines.append('from pine_engine.runtime.series import Series')
        lines.append('from pine_engine.runtime.builtins import (')
        lines.append('    pine_hour, pine_minute, pine_dayofweek,')
        lines.append('    pine_year, pine_month, pine_dayofmonth,')
        lines.append('    ta_pivothigh, ta_pivotlow, ta_highest, ta_lowest,')
        lines.append('    ta_rsi, ta_crossover, ta_crossunder')
        lines.append(')')
        lines.append('from pine_engine.runtime.strategy import STRATEGY_LONG, STRATEGY_SHORT')
        lines.append('')
        lines.append('')

        # Generate initialize function
        lines.append('def initialize(ctx):')
        lines.append('    """Initialize var declarations (run once on bar 0)."""')
        init_lines = self._gen_initialize()
        if init_lines:
            lines.extend(init_lines)
        else:
            lines.append('    pass')
        lines.append('')
        lines.append('')

        # Generate execute_bar function
        lines.append('def execute_bar(ctx):')
        lines.append('    """Execute one bar of Pine Script logic."""')
        self.indent_level = 1
        exec_lines = self._gen_execute_bar()
        if exec_lines:
            lines.extend(exec_lines)
        else:
            lines.append('    pass')

        return '\n'.join(lines)

    def _gen_initialize(self) -> List[str]:
        """Generate initialization code for var declarations."""
        lines = []
        ind = '    '

        # Initialize built-in series
        lines.append(f'{ind}# Built-in series')
        for name in sorted(BUILTIN_SERIES):
            lines.append(f'{ind}ctx.{name} = Series(max_lookback=100)')

        lines.append(f'{ind}')
        lines.append(f'{ind}# User series (variables used with [N])')
        for name in sorted(self.series_vars - BUILTIN_SERIES):
            if name not in self.skip_vars:
                lines.append(f'{ind}ctx.series_{name} = Series(max_lookback=100)')

        lines.append(f'{ind}')
        lines.append(f'{ind}# Persistent var declarations')
        for stmt in self.program.statements:
            if isinstance(stmt, VarDeclaration) and (stmt.is_var or stmt.is_varip):
                if stmt.name in self.skip_vars:
                    continue
                init_val = self._gen_expr(stmt.initializer)
                lines.append(f'{ind}ctx.v_{stmt.name} = {init_val}')

        return lines

    def _gen_execute_bar(self) -> List[str]:
        """Generate the main execute_bar body."""
        lines = []
        ind = '    '

        # Update built-in series from current bar
        lines.append(f'{ind}# Update built-in series')
        lines.append(f'{ind}ctx.time.append(ctx.bar_ts_ms)')
        lines.append(f'{ind}ctx.open.append(ctx.bar_open)')
        lines.append(f'{ind}ctx.high.append(ctx.bar_high)')
        lines.append(f'{ind}ctx.low.append(ctx.bar_low)')
        lines.append(f'{ind}ctx.close.append(ctx.bar_close)')
        lines.append(f'{ind}ctx.bar_index.append(ctx.bar_idx)')
        lines.append(f'{ind}')

        # Generate statements (skip strategy declaration, func defs, and skip-targeted code)
        for stmt in self.program.statements:
            if isinstance(stmt, (StrategyDeclaration, IndicatorDeclaration, FunctionDef)):
                continue
            stmt_lines = self._gen_statement(stmt, indent=1)
            if stmt_lines:
                lines.extend(stmt_lines)

        return lines

    def _gen_statement(self, stmt, indent: int) -> List[str]:
        """Generate Python code for a statement."""
        ind = '    ' * indent

        if isinstance(stmt, VarDeclaration):
            return self._gen_var_decl(stmt, indent)
        elif isinstance(stmt, Assignment):
            return self._gen_assignment(stmt, indent)
        elif isinstance(stmt, IfStatement):
            return self._gen_if(stmt, indent)
        elif isinstance(stmt, ForStatement):
            return self._gen_for(stmt, indent)
        elif isinstance(stmt, WhileStatement):
            return self._gen_while(stmt, indent)
        elif isinstance(stmt, BreakStatement):
            return [f'{ind}break']
        elif isinstance(stmt, ExprStatement):
            return self._gen_expr_stmt(stmt, indent)
        return []

    def _gen_var_decl(self, stmt: VarDeclaration, indent: int) -> List[str]:
        """Generate variable declaration."""
        ind = '    ' * indent
        name = stmt.name

        if name in self.skip_vars:
            return [f'{ind}# SKIP (viz): {name}']

        val = self._gen_expr(stmt.initializer)

        if stmt.is_var or stmt.is_varip:
            # var declarations are initialized in initialize(), not here
            return []
        else:
            # Regular declaration — re-initialized each bar
            py_name = self._var_ref(name)
            return [f'{ind}{py_name} = {val}']

    def _gen_assignment(self, stmt: Assignment, indent: int) -> List[str]:
        """Generate reassignment."""
        ind = '    ' * indent
        name = stmt.target

        if name in self.skip_vars:
            return [f'{ind}# SKIP (viz): {name}']

        val = self._gen_expr(stmt.value)
        py_name = self._var_ref(name)
        return [f'{ind}{py_name} = {val}']

    def _gen_if(self, stmt: IfStatement, indent: int) -> List[str]:
        """Generate if/elif/else."""
        ind = '    ' * indent
        lines = []

        cond = self._gen_expr(stmt.condition)
        lines.append(f'{ind}if {cond}:')

        body_lines = []
        for s in stmt.then_body:
            body_lines.extend(self._gen_statement(s, indent + 1))
        if not body_lines:
            body_lines = [f'{ind}    pass']
        lines.extend(body_lines)

        for elif_cond, elif_body in stmt.elif_branches:
            ec = self._gen_expr(elif_cond)
            lines.append(f'{ind}elif {ec}:')
            eb_lines = []
            for s in elif_body:
                eb_lines.extend(self._gen_statement(s, indent + 1))
            if not eb_lines:
                eb_lines = [f'{ind}    pass']
            lines.extend(eb_lines)

        if stmt.else_body:
            lines.append(f'{ind}else:')
            else_lines = []
            for s in stmt.else_body:
                else_lines.extend(self._gen_statement(s, indent + 1))
            if not else_lines:
                else_lines = [f'{ind}    pass']
            lines.extend(else_lines)

        return lines

    def _gen_for(self, stmt: ForStatement, indent: int) -> List[str]:
        """Generate for loop."""
        ind = '    ' * indent
        lines = []

        start = self._gen_expr(stmt.start)
        end = self._gen_expr(stmt.end)
        lines.append(f'{ind}for {stmt.var_name} in range(int({start}), int({end}) + 1):')

        body_lines = []
        for s in stmt.body:
            body_lines.extend(self._gen_statement(s, indent + 1))
        if not body_lines:
            body_lines = [f'{ind}    pass']
        lines.extend(body_lines)

        return lines

    def _gen_while(self, stmt: WhileStatement, indent: int) -> List[str]:
        """Generate while loop (mostly viz code — but generate correctly)."""
        ind = '    ' * indent
        lines = []
        cond = self._gen_expr(stmt.condition)
        lines.append(f'{ind}while {cond}:')
        body_lines = []
        for s in stmt.body:
            body_lines.extend(self._gen_statement(s, indent + 1))
        if not body_lines:
            body_lines = [f'{ind}    pass']
        lines.extend(body_lines)
        return lines

    def _gen_expr_stmt(self, stmt: ExprStatement, indent: int) -> List[str]:
        """Generate expression statement (function calls)."""
        ind = '    ' * indent
        expr = stmt.expr

        if isinstance(expr, FunctionCall):
            if self._is_skip_func(expr.name):
                return [f'{ind}pass  # SKIP: {expr.name}']

            code = self._gen_func_call(expr)
            return [f'{ind}{code}']

        code = self._gen_expr(expr)
        return [f'{ind}{code}']

    # ── Expression generation ──

    def _gen_expr(self, expr) -> str:
        """Generate Python expression string."""
        if expr is None:
            return 'NA'

        if isinstance(expr, NumberLiteral):
            return str(expr.value)

        if isinstance(expr, StringLiteral):
            # Escape for Python string
            escaped = expr.value.replace('\\', '\\\\').replace('"', '\\"')
            return f'"{escaped}"'

        if isinstance(expr, BoolLiteral):
            return 'True' if expr.value else 'False'

        if isinstance(expr, NaLiteral):
            return 'NA'

        if isinstance(expr, Identifier):
            return self._resolve_identifier(expr.name)

        if isinstance(expr, BinaryOp):
            return self._gen_binary(expr)

        if isinstance(expr, UnaryOp):
            return self._gen_unary(expr)

        if isinstance(expr, Ternary):
            cond = self._gen_expr(expr.condition)
            t = self._gen_expr(expr.true_expr)
            f = self._gen_expr(expr.false_expr)
            return f'({t} if {cond} else {f})'

        if isinstance(expr, HistoryRef):
            return self._gen_history_ref(expr)

        if isinstance(expr, FunctionCall):
            return self._gen_func_call(expr)

        if isinstance(expr, MemberAccess):
            obj = self._gen_expr(expr.object)
            return f'{obj}.{expr.member}'

        return f'None  # UNKNOWN: {type(expr).__name__}'

    def _gen_binary(self, expr: BinaryOp) -> str:
        """Generate binary operation with NA-aware operators for and/or."""
        left = self._gen_expr(expr.left)
        right = self._gen_expr(expr.right)

        if expr.op == 'and':
            return f'pine_and({left}, {right})'
        if expr.op == 'or':
            return f'pine_or({left}, {right})'
        if expr.op == '==':
            return f'pine_eq({left}, {right})'
        if expr.op == '!=':
            return f'pine_neq({left}, {right})'
        if expr.op == '<':
            return f'pine_lt({left}, {right})'
        if expr.op == '>':
            return f'pine_gt({left}, {right})'
        if expr.op == '<=':
            return f'pine_lte({left}, {right})'
        if expr.op == '>=':
            return f'pine_gte({left}, {right})'

        op = OP_MAP.get(expr.op, expr.op)
        return f'({left} {op} {right})'

    def _gen_unary(self, expr: UnaryOp) -> str:
        operand = self._gen_expr(expr.operand)
        if expr.op == 'not':
            return f'pine_not({operand})'
        if expr.op == '-':
            return f'(-{operand})'
        return f'({expr.op}{operand})'

    def _gen_history_ref(self, expr: HistoryRef) -> str:
        """Generate series[offset] access."""
        offset = self._gen_expr(expr.offset)

        if isinstance(expr.series, Identifier):
            name = expr.series.name
            if name in BUILTIN_SERIES:
                return f'ctx.{name}[{offset}]'
            if name in self.var_names:
                # var variables aren't series — history doesn't apply
                # But Pine allows it, so wrap in a check
                return f'ctx.v_{name}'  # Just return current value
            if name in self.series_vars:
                return f'ctx.series_{name}[{offset}]'
            # Fallback — local variable, no history
            return f'{name}'

        series = self._gen_expr(expr.series)
        return f'{series}[{offset}]'

    def _gen_func_call(self, expr: FunctionCall) -> str:
        """Generate function call."""
        name = expr.name

        # Skip visualization functions — return safe value for expressions
        if self._is_skip_func(name):
            return 'NA'

        # Strategy API calls
        if name == 'strategy.order':
            return self._gen_strategy_order(expr)
        if name == 'strategy.exit':
            return self._gen_strategy_exit(expr)
        if name == 'strategy.cancel':
            args = [self._gen_expr(a) for a in expr.args]
            return f'ctx.strategy.cancel({args[0]})'
        if name == 'strategy.opentrades.entry_comment':
            args = [self._gen_expr(a) for a in expr.args]
            return f'ctx.strategy.opentrades.entry_comment(int({args[0]}))'
        if name == 'strategy.opentrades.entry_price':
            args = [self._gen_expr(a) for a in expr.args]
            return f'ctx.strategy.opentrades.entry_price(int({args[0]}))'
        if name == 'strategy.closedtrades.exit_comment':
            args = [self._gen_expr(a) for a in expr.args]
            return f'ctx.strategy.closedtrades.exit_comment(int({args[0]}))'

        # Built-in function mapping
        if name in BUILTIN_MAP:
            py_name = BUILTIN_MAP[name]
            args = self._gen_call_args(expr)
            # For ta.* functions, first arg might need to be a Series reference
            if name.startswith('ta.pivot') or name.startswith('ta.highest') or name.startswith('ta.lowest'):
                return self._gen_ta_call(py_name, expr)
            return f'{py_name}({args})'

        # Input functions → parameter lookup
        if name.startswith('input.'):
            # This should have been captured during parsing
            # Generate a ctx.params lookup
            return f'ctx.params.get("{name}", NA)'

        # Unknown function — generate as-is (will error at runtime if truly needed)
        args = self._gen_call_args(expr)
        return f'{name}({args})'

    def _gen_strategy_order(self, expr: FunctionCall) -> str:
        parts = []
        if len(expr.args) >= 1:
            parts.append(f'id={self._gen_expr(expr.args[0])}')
        if len(expr.args) >= 2:
            parts.append(f'direction={self._gen_expr(expr.args[1])}')
        for k, v in expr.kwargs.items():
            parts.append(f'{k}={self._gen_expr(v)}')
        return f'ctx.strategy.order({", ".join(parts)})'

    def _gen_strategy_exit(self, expr: FunctionCall) -> str:
        parts = []
        if len(expr.args) >= 1:
            parts.append(f'id={self._gen_expr(expr.args[0])}')
        for k, v in expr.kwargs.items():
            parts.append(f'{k}={self._gen_expr(v)}')
        return f'ctx.strategy.exit({", ".join(parts)})'

    def _gen_ta_call(self, py_name: str, expr: FunctionCall) -> str:
        """Generate ta.* function calls with Series argument handling."""
        args = []
        for i, a in enumerate(expr.args):
            if i == 0 and isinstance(a, Identifier):
                # First arg to ta.* is typically a series (high, low, close, etc.)
                name = a.name
                if name in BUILTIN_SERIES:
                    args.append(f'ctx.{name}')
                elif name in self.series_vars:
                    args.append(f'ctx.series_{name}')
                else:
                    args.append(self._gen_expr(a))
            else:
                args.append(self._gen_expr(a))
        for k, v in expr.kwargs.items():
            args.append(f'{k}={self._gen_expr(v)}')
        return f'{py_name}({", ".join(args)})'

    def _gen_call_args(self, expr: FunctionCall) -> str:
        """Generate comma-separated argument list."""
        parts = []
        for a in expr.args:
            parts.append(self._gen_expr(a))
        for k, v in expr.kwargs.items():
            parts.append(f'{k}={self._gen_expr(v)}')
        return ', '.join(parts)

    def _resolve_identifier(self, name: str) -> str:
        """Resolve an identifier to its Python equivalent."""
        # Check constants first
        if name in CONSTANT_MAP:
            return CONSTANT_MAP[name]

        # Built-in series (current value)
        if name in BUILTIN_SERIES:
            return f'ctx.{name}[0]'

        # Strategy properties
        if name == 'strategy.opentrades':
            return 'ctx.strategy.opentrades'
        if name == 'strategy.closedtrades':
            return 'ctx.strategy.closedtrades'

        # Persistent var
        if name in self.var_names:
            return f'ctx.v_{name}'

        # Skip vars (viz)
        if name in self.skip_vars:
            return 'None'

        # Regular local variable
        return name

    def _var_ref(self, name: str) -> str:
        """Get the Python reference for assigning to a variable."""
        if name in self.var_names:
            return f'ctx.v_{name}'
        if name in self.skip_vars:
            return f'_skip_{name}'
        return name


def generate_code(program: Program, inputs: Dict) -> str:
    """Generate Python source from Pine AST.

    Returns:
        Python source code string ready for exec()
    """
    gen = CodeGenerator(program, inputs)
    return gen.generate()
