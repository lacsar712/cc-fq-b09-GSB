"""弱位点阈值规则与重算的单元测试。"""

import pytest

from app.pipeline.actors import apply_weak_floor, compute_weak_positions
from app.pipeline.runner import _run_chain


GOOD_FASTQ = """@SEQ1
ACGTACGT
+
IIIIHHHH
@SEQ2
NNNNACGT
+
IIIIIIII
"""

# 各位点质量（I=40, H=39）：
# 位点 1-4 全为 I → 40；位点 5-8 第一读段 H(39)、第二读段 I(40) → 39.5
EXPECTED_PER_POS = [40, 40, 40, 40, 39.5, 39.5, 39.5, 39.5]


@pytest.mark.asyncio
async def test_weak_positions_written_at_success():
    ok, ctx, _stages = await _run_chain(GOOD_FASTQ, quality_floor=28.0)
    assert ok is True
    per_pos = ctx.metrics["per_position"]
    assert [p["mean_quality"] for p in per_pos] == EXPECTED_PER_POS
    # 阈值 28：全部位点远高于 28 → 空清单
    assert ctx.metrics["weak_positions"] == []
    assert ctx.metrics["weak_quality_floor"] == 28.0


@pytest.mark.asyncio
async def test_weak_positions_high_floor_nonempty_and_rule_consistent():
    """自测核心：把下限调高后，弱位点清单非空且与阈值规则严格一致。"""
    floor = 39.7
    ok, ctx, _stages = await _run_chain(GOOD_FASTQ, quality_floor=floor)
    assert ok is True
    weak = ctx.metrics["weak_positions"]
    # 位点 5-8 质量 39.5 < 39.7 应为弱位点；位点 1-4 质量 40 不应入选
    assert [w["position"] for w in weak] == [5, 6, 7, 8]
    assert all(w["mean_quality"] == 39.5 for w in weak)
    # 与纯函数阈值规则完全一致
    expected = compute_weak_positions(ctx.metrics["per_position"], floor)
    assert weak == expected


@pytest.mark.asyncio
async def test_weak_boundary_is_strict_less_than():
    """等于阈值的位点不算弱位点（严格小于）。"""
    floor = 39.5
    ok, ctx, _stages = await _run_chain(GOOD_FASTQ, quality_floor=floor)
    assert ok is True
    assert ctx.metrics["weak_positions"] == []


@pytest.mark.asyncio
async def test_weak_in_report_and_summary_copies():
    ok, ctx, _stages = await _run_chain(GOOD_FASTQ, quality_floor=39.7)
    assert ok is True
    assert [w["position"] for w in ctx.metrics["report"]["weak_positions"]] == [5, 6, 7, 8]
    assert ctx.metrics["report"]["weak_quality_floor"] == 39.7
    assert ctx.metrics["summary"]["weak_positions_count"] == 4


def test_apply_weak_floor_recompute_syncs_copies():
    """对已成功作业的指标按新阈值重算：只动清单，不动 per_position，副本同步。"""
    metrics = {
        "per_position": [
            {"position": 1, "mean_quality": 40.0},
            {"position": 2, "mean_quality": 30.0},
            {"position": 3, "mean_quality": 25.0},
        ],
        "report": {"weak_positions": [], "weak_quality_floor": 20.0},
        "summary": {"weak_positions_count": 0, "weak_quality_floor": 20.0},
    }
    apply_weak_floor(metrics, 35.0)
    assert [w["position"] for w in metrics["weak_positions"]] == [2, 3]
    assert metrics["weak_quality_floor"] == 35.0
    assert metrics["report"]["weak_positions"] == metrics["weak_positions"]
    assert metrics["summary"]["weak_positions_count"] == 2
    # 再次调低阈值，清单收缩
    apply_weak_floor(metrics, 28.0)
    assert [w["position"] for w in metrics["weak_positions"]] == [3]


def test_compute_weak_positions_empty_input():
    assert compute_weak_positions(None, 30) == []
    assert compute_weak_positions([], 30) == []
