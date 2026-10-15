"""strategy.entry ist seit P1b unterstuetzt (Pyramiding + Reversal) und bleibt
von strategy.order getrennt — kein Alias."""
from pathlib import Path
import sys
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from pine_engine.engine import compile_pine

@pytest.mark.parametrize('source,expect',[
    ('strategy.entry("L", strategy.long, qty=1, limit=100)', 'ctx.strategy.entry(id="L", direction=STRATEGY_LONG, qty=1, limit=100'),
    ('strategy.entry(id="S", direction=strategy.short, qty=2)', 'ctx.strategy.entry(id="S", direction=STRATEGY_SHORT, qty=2)'),
    ('if false\n    strategy.entry("L", strategy.long, qty=1, limit=100)', 'ctx.strategy.entry('),
])
def test_entry_compiles_to_entry_not_order(source, expect):
    code = compile_pine(source).python_code
    assert expect in code
    assert 'ctx.strategy.order(' not in code

def test_order_keeps_distinct_supported_codegen():
    code=compile_pine('strategy.order("L", strategy.long, qty=1, limit=100)').python_code
    assert 'ctx.strategy.order(' in code
    assert 'strategy.entry(' not in code
