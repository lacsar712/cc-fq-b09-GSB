"""Unit tests for Actor pipeline (no DB required)."""

import asyncio

import pytest

from app.pipeline.actors import (
    DEFAULT_WEAK_THRESHOLD,
    ActorError,
    NContentActor,
    ParseActor,
    PipelineContext,
    QualityHistActor,
    QueueMessage,
    ReportActor,
    compute_weak_positions,
)
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

BROKEN_FASTQ = """@SEQ1
ACGT
NOTPLUS
IIII
"""


@pytest.mark.asyncio
async def test_parse_actor_rejects_malformed():
    actor = ParseActor()
    in_q: asyncio.Queue = asyncio.Queue()
    out_q: asyncio.Queue = asyncio.Queue()
    await in_q.put(QueueMessage(ok=True, context=PipelineContext(fastq_text=BROKEN_FASTQ)))
    await actor.run(in_q, out_q)
    result = await out_q.get()
    assert result.ok is False
    assert "必须以 +" in (result.error or "")


@pytest.mark.asyncio
async def test_parse_actor_ok_and_quality_mean():
    ok, ctx, stages = await _run_chain(GOOD_FASTQ)
    assert ok is True
    assert stages["ParseActor"]["status"] == "success"
    assert stages["ReportActor"]["status"] == "success"
    assert ctx.metrics["reads"] == 2
    assert "mean_quality" in ctx.metrics
    assert ctx.metrics["mean_quality"] > 0
    assert ctx.metrics["n_rate"] == 0.25  # 4 N out of 16 bases


@pytest.mark.asyncio
async def test_broken_stops_pipeline():
    ok, ctx, stages = await _run_chain(BROKEN_FASTQ)
    assert ok is False
    assert stages["ParseActor"]["status"] == "failed"
    assert stages["QualityHistActor"]["status"] == "skipped"
    assert stages["NContentActor"]["status"] == "skipped"
    assert stages["ReportActor"]["status"] == "skipped"
    assert ctx.failed_actor == "ParseActor"


def test_parse_length_mismatch():
    actor = ParseActor()
    with pytest.raises(ActorError, match="长度不一致"):
        actor._parse("@A\nACGT\n+\nII\n")


def test_compute_weak_positions_rule():
    per = [
        {"position": 1, "mean_quality": 40.0},
        {"position": 2, "mean_quality": 29.9},
        {"position": 3, "mean_quality": 30.0},
    ]
    # 严格小于阈值才算弱位点；等于阈值不算
    assert compute_weak_positions(per, 30.0) == [{"position": 2, "mean_quality": 29.9}]
    assert compute_weak_positions(None, 30.0) == []
    assert compute_weak_positions([], 30.0) == []


@pytest.mark.asyncio
async def test_weak_positions_empty_under_default_threshold():
    ok, ctx, _ = await _run_chain(GOOD_FASTQ)
    assert ok is True
    assert ctx.metrics["weak_threshold"] == DEFAULT_WEAK_THRESHOLD
    assert ctx.metrics["weak_positions"] == []


@pytest.mark.asyncio
async def test_weak_positions_with_raised_threshold():
    # GOOD_FASTQ 位点 1-4 平均质量 40.0，位点 5-8 平均质量 39.5
    ok, ctx, _ = await _run_chain(GOOD_FASTQ, weak_threshold=40.0)
    assert ok is True
    weak = ctx.metrics["weak_positions"]
    assert ctx.metrics["weak_threshold"] == 40.0
    assert [w["position"] for w in weak] == [5, 6, 7, 8]
    assert all(w["mean_quality"] < 40.0 for w in weak)
    assert ctx.metrics["report"]["weak_count"] == 4
    assert ctx.metrics["summary"]["weak_count"] == 4


@pytest.mark.asyncio
async def test_failed_chain_has_no_weak_positions():
    ok, ctx, _ = await _run_chain(BROKEN_FASTQ)
    assert ok is False
    assert "weak_positions" not in ctx.metrics
