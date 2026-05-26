"""管道可观测性追踪器 — 记录每个标的在每步的状态"""
from __future__ import annotations

import functools
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable
from uuid import uuid4

logger = logging.getLogger(__name__)


@dataclass
class StepResult:
    """单步执行结果"""
    stock_code: str
    stock_name: str = ""
    action: str = "passed"  # passed / filtered / scored / promoted / demoted
    score_before: float | None = None
    score_after: float | None = None
    reason: str = ""
    detail: dict | None = None


@dataclass
class PipelineContext:
    """管道上下文，贯穿全流程"""
    execution_id: str = field(default_factory=lambda: str(uuid4()))
    execution_date: str = ""
    trigger_type: str = "scheduled"
    strategy_id: str = ""
    market: str = "ALL"
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # 每步的追踪记录 step_name -> list[StepResult]
    traces: dict[str, list[StepResult]] = field(default_factory=dict)
    # 每步的统计
    step_stats: dict[str, dict] = field(default_factory=dict)

    def add_trace(self, step_name: str, result: StepResult):
        if step_name not in self.traces:
            self.traces[step_name] = []
        self.traces[step_name].append(result)

    def add_step_stats(self, step_name: str, input_count: int, output_count: int, duration_ms: int):
        self.step_stats[step_name] = {
            "input_count": input_count,
            "output_count": output_count,
            "filtered_count": input_count - output_count,
            "duration_ms": duration_ms,
        }

    def total_traces(self) -> int:
        return sum(len(v) for v in self.traces.values())


def tracked_step(step_name: str, step_order: int):
    """
    管道步骤装饰器 — 自动记录输入输出数量和耗时。

    被装饰的函数签名必须接受 ctx: PipelineContext 关键字参数。
    第一个位置参数视为候选列表（用于统计输入数量）。
    """
    def decorator(func: Callable):
        @functools.wraps(func)
        async def async_wrapper(*args, ctx: PipelineContext, **kwargs):
            input_data = args[0] if args else kwargs.get("candidates", [])
            input_count = len(input_data) if hasattr(input_data, "__len__") else 0

            start = time.monotonic()
            logger.info("[Pipeline] Step %d: %s | input=%d", step_order, step_name, input_count)

            try:
                result = await func(*args, ctx=ctx, **kwargs)
                output_count = len(result) if hasattr(result, "__len__") else 0
                duration_ms = int((time.monotonic() - start) * 1000)

                ctx.add_step_stats(step_name, input_count, output_count, duration_ms)
                logger.info(
                    "[Pipeline] Step %d: %s | output=%d | filtered=%d | %dms",
                    step_order, step_name, output_count, input_count - output_count, duration_ms,
                )
                return result
            except Exception as e:
                duration_ms = int((time.monotonic() - start) * 1000)
                logger.error(
                    "[Pipeline] Step %d: %s FAILED | %dms | %s",
                    step_order, step_name, duration_ms, e,
                )
                ctx.add_step_stats(step_name, input_count, 0, duration_ms)
                raise

        @functools.wraps(func)
        def sync_wrapper(*args, ctx: PipelineContext, **kwargs):
            input_data = args[0] if args else kwargs.get("candidates", [])
            input_count = len(input_data) if hasattr(input_data, "__len__") else 0

            start = time.monotonic()
            logger.info("[Pipeline] Step %d: %s | input=%d", step_order, step_name, input_count)

            try:
                result = func(*args, ctx=ctx, **kwargs)
                output_count = len(result) if hasattr(result, "__len__") else 0
                duration_ms = int((time.monotonic() - start) * 1000)

                ctx.add_step_stats(step_name, input_count, output_count, duration_ms)
                logger.info(
                    "[Pipeline] Step %d: %s | output=%d | filtered=%d | %dms",
                    step_order, step_name, output_count, input_count - output_count, duration_ms,
                )
                return result
            except Exception as e:
                duration_ms = int((time.monotonic() - start) * 1000)
                logger.error(
                    "[Pipeline] Step %d: %s FAILED | %dms | %s",
                    step_order, step_name, duration_ms, e,
                )
                ctx.add_step_stats(step_name, input_count, 0, duration_ms)
                raise

        import asyncio
        if asyncio.iscoroutinefunction(func):
            wrapper = async_wrapper
        else:
            wrapper = sync_wrapper
        wrapper._step_name = step_name
        wrapper._step_order = step_order
        return wrapper
    return decorator
