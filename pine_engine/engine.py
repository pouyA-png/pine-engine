"""Pine Engine — the main execution harness.

Wires together: Lexer → Parser → Codegen → Runtime → Strategy → Data
Provides the top-level API for running a .pine file against bar data.

Execution model (calc_on_every_tick=false):
  For each bar:
    1. strategy.process_bar(bar)     ← fill pending entries + exits
    2. update ctx with bar data      ← built-in series + bar fields
    3. execute_bar(ctx)              ← run transpiled Pine logic
"""

from __future__ import annotations
from typing import Dict, List, Optional, Any
from pathlib import Path

from pine_engine.lexer import tokenize
from pine_engine.parser import parse
from pine_engine.codegen import generate_code
from pine_engine.runtime.series import Series
from pine_engine.runtime.na import NA, is_na
from pine_engine.runtime.strategy import StrategyAPI
from pine_engine.runtime.broker import Bar, ClosedTrade
from pine_engine.data.loader import load_bars_csv, bar_timestamp_ms


class RuntimeContext:
    """Holds all state during Pine Script execution.

    The transpiled code accesses everything through `ctx`:
      ctx.time, ctx.open, ctx.high, ctx.low, ctx.close, ctx.bar_index  (Series)
      ctx.v_*             (persistent var declarations)
      ctx.strategy         (StrategyAPI)
      ctx.params            (input parameters)
      ctx.bar_ts_ms, ctx.bar_open, ctx.bar_high, etc.  (current bar scalars)
    """

    def __init__(self, params: Dict[str, Any] = None):
        self.params = params or {}
        self.strategy = StrategyAPI()

        # Current bar scalars (updated each bar before execute_bar runs)
        self.bar_ts_ms: int = 0
        self.bar_open: float = 0.0
        self.bar_high: float = 0.0
        self.bar_low: float = 0.0
        self.bar_close: float = 0.0
        self.bar_idx: int = 0

    def update_bar(self, bar: Bar):
        """Set current bar data before executing Pine logic."""
        self.bar_ts_ms = bar_timestamp_ms(bar)
        self.bar_open = bar.open
        self.bar_high = bar.high
        self.bar_low = bar.low
        self.bar_close = bar.close
        self.bar_idx = bar.bar_index


class CompiledPine:
    """A compiled Pine Script ready for execution."""

    def __init__(self, source_path: str, python_code: str,
                 inputs: Dict, strategy_settings: Dict):
        self.source_path = source_path
        self.python_code = python_code
        self.inputs = inputs
        self.strategy_settings = strategy_settings

        # Compile and extract functions
        self._module = {}
        exec(compile(python_code, f'<pine:{source_path}>', 'exec'), self._module)
        self.initialize = self._module['initialize']
        self.execute_bar = self._module['execute_bar']

    def get_default_params(self) -> Dict[str, Any]:
        """Get default parameter values from input declarations."""
        params = {}
        for name, info in self.inputs.items():
            if 'default' in info and info['default'] is not None:
                params[name] = info['default']
        return params


def compile_pine(source_or_path: str) -> CompiledPine:
    """Compile a Pine Script source string or file path.

    Args:
        source_or_path: Either Pine source code string or path to .pine file

    Returns:
        CompiledPine object ready for execution
    """
    # Detect if input is a file path or source string
    is_path = len(source_or_path) < 500 and '\n' not in source_or_path
    if is_path:
        path = Path(source_or_path)
        if path.exists():
            source = path.read_text()
            source_name = path.name
        else:
            source = source_or_path
            source_name = '<string>'
    else:
        source = source_or_path
        source_name = '<string>'

    tokens = tokenize(source)
    program, inputs = parse(tokens)
    python_code = generate_code(program, inputs)

    # Extract strategy settings
    strategy_settings = {}
    for stmt in program.statements:
        if hasattr(stmt, 'kwargs') and hasattr(stmt, 'name'):
            if hasattr(stmt, '__class__') and stmt.__class__.__name__ == 'StrategyDeclaration':
                strategy_settings = stmt.kwargs
                break

    return CompiledPine(source_name, python_code, inputs, strategy_settings)


def run_backtest(compiled: CompiledPine,
                 bars: List[Bar],
                 params: Optional[Dict[str, Any]] = None) -> List[ClosedTrade]:
    """Run a backtest of compiled Pine Script on bar data.

    Args:
        compiled: CompiledPine from compile_pine()
        bars: List of Bar objects (chronological order)
        params: Parameter overrides (merged with defaults from input declarations)

    Returns:
        List of ClosedTrade objects
    """
    # Build parameters: defaults + overrides
    effective_params = compiled.get_default_params()
    if params:
        effective_params.update(params)

    # Create runtime context
    ctx = RuntimeContext(params=effective_params)

    # Initialize (var declarations)
    compiled.initialize(ctx)

    # Execute bar by bar
    for bar in bars:
        # 1. Process pending entries + exits BEFORE running script
        ctx.strategy.process_bar(bar)

        # 2. Update context with current bar data
        ctx.update_bar(bar)

        # 3. Run transpiled Pine logic
        compiled.execute_bar(ctx)

    return ctx.strategy.get_results()


def run_pine_file(pine_path: str,
                  data_path: str,
                  params: Optional[Dict[str, Any]] = None,
                  start_date: Optional[str] = None,
                  end_date: Optional[str] = None) -> List[ClosedTrade]:
    """Convenience: compile + load data + run backtest in one call.

    Args:
        pine_path: Path to .pine file
        data_path: Path to CSV data file
        params: Parameter overrides
        start_date: Optional "YYYY-MM-DD" filter
        end_date: Optional "YYYY-MM-DD" filter

    Returns:
        List of ClosedTrade objects
    """
    compiled = compile_pine(pine_path)
    bars = load_bars_csv(data_path, start_date=start_date, end_date=end_date)
    return run_backtest(compiled, bars, params)
