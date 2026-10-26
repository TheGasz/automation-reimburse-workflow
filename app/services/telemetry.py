"""Observability telemetry decorator and metrics calculator for KlaimKilat AI."""

from __future__ import annotations

import functools
import math
import time
from collections.abc import Awaitable, Callable
from typing import Any

from app.config import get_settings
from app.db.session import db_manager


def estimate_cost_idr(prompt_tokens: int, completion_tokens: int) -> float:
    """Calculate estimated LLM token cost in IDR based on DeepSeek pricing."""
    settings = get_settings()
    prompt_cost = (prompt_tokens / 1000.0) * settings.cost_per_1k_prompt_tokens_idr
    completion_cost = (
        completion_tokens / 1000.0
    ) * settings.cost_per_1k_completion_tokens_idr
    return round(prompt_cost + completion_cost, 4)


def track_node_telemetry(
    node_name: str,
) -> Callable[
    [Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]],
    Callable[[dict[str, Any]], Awaitable[dict[str, Any]]],
]:
    """Decorator that records node latency_ms, token counts, cost_idr, and errors."""

    def decorator(
        func: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]],
    ) -> Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]:
        @functools.wraps(func)
        async def wrapper(state: dict[str, Any]) -> dict[str, Any]:
            start_ts = time.perf_counter()
            claim_id = str(state.get("claim_id", "UNKNOWN"))
            existing_telemetry = dict(state.get("telemetry") or {})
            nodes_metrics = dict(existing_telemetry.get("nodes") or {})
            errors_list = list(existing_telemetry.get("errors") or [])

            status = "SUCCESS"
            error_msg: str | None = None
            result: dict[str, Any] = {}

            try:
                result = await func(state)
                return result
            except Exception as exc:
                status = "ERROR"
                error_msg = f"{type(exc).__name__}: {exc}"
                errors_list.append({"node": node_name, "error": error_msg})
                raise
            finally:
                elapsed_ms = round((time.perf_counter() - start_ts) * 1000.0, 2)
                node_meta = (result.get("_node_usage") if isinstance(result, dict) else None) or {}
                prompt_tokens = int(node_meta.get("prompt_tokens", 0))
                completion_tokens = int(node_meta.get("completion_tokens", 0))
                cost_idr = estimate_cost_idr(prompt_tokens, completion_tokens)

                if isinstance(result, dict) and "_node_usage" in result:
                    result.pop("_node_usage", None)

                nodes_metrics[node_name] = {
                    "latency_ms": elapsed_ms,
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": prompt_tokens + completion_tokens,
                    "cost_idr": cost_idr,
                    "status": status,
                }

                total_latency = round(
                    sum(float(m.get("latency_ms", 0.0)) for m in nodes_metrics.values()),
                    2,
                )
                total_tokens = sum(
                    int(m.get("total_tokens", 0)) for m in nodes_metrics.values()
                )
                total_cost_idr = round(
                    sum(float(m.get("cost_idr", 0.0)) for m in nodes_metrics.values()),
                    4,
                )

                updated_telemetry = {
                    "nodes": nodes_metrics,
                    "total_latency_ms": total_latency,
                    "total_tokens": total_tokens,
                    "total_cost_idr": total_cost_idr,
                    "errors": errors_list,
                }
                if isinstance(result, dict):
                    result["telemetry"] = updated_telemetry

                await db_manager.record_telemetry(
                    claim_id=claim_id,
                    node_name=node_name,
                    latency_ms=elapsed_ms,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    cost_idr=cost_idr,
                    status=status,
                    error_message=error_msg,
                )

        return wrapper

    return decorator


def compute_percentile(values: list[float], percentile: float) -> float:
    """Compute percentile (e.g., p50 or p95) from a list of floats."""
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    idx = (len(sorted_vals) - 1) * (percentile / 100.0)
    lower = math.floor(idx)
    upper = math.ceil(idx)
    if lower == upper:
        return round(sorted_vals[int(idx)], 2)
    weight = idx - lower
    return round(sorted_vals[lower] * (1.0 - weight) + sorted_vals[upper] * weight, 2)
