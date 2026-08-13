"""Honest generation progress: active tasks ramp to half weight, then finish to full."""

from __future__ import annotations

from dataclasses import dataclass

ACTIVE_RAMP_SECONDS = 30.0
ACTIVE_WEIGHT_CAP = 0.5
FINISH_RAMP_SECONDS = 10.0


@dataclass
class TaskProgress:
    started_at: float
    finishing_at: float | None = None
    finish_from: float = 0.0
    step_id: int = 0


def active_fraction(elapsed: float) -> float:
    if elapsed <= 0:
        return 0.0
    return ACTIVE_WEIGHT_CAP * min(1.0, elapsed / ACTIVE_RAMP_SECONDS)


def finishing_fraction(finish_from: float, elapsed: float) -> float:
    if elapsed <= 0:
        return finish_from
    if elapsed >= FINISH_RAMP_SECONDS:
        return 1.0
    return finish_from + (1.0 - finish_from) * (elapsed / FINISH_RAMP_SECONDS)


def task_weight_fraction(task: TaskProgress, now: float) -> float:
    if task.finishing_at is not None:
        return finishing_fraction(task.finish_from, now - task.finishing_at)
    return active_fraction(now - task.started_at)


def displayed_percent(total_tasks: int, tasks: list[TaskProgress], now: float) -> float:
    if total_tasks <= 0:
        return 0.0
    unit = 100.0 / total_tasks
    return sum(unit * task_weight_fraction(task, now) for task in tasks)


def format_progress_percent(percent: float) -> str:
    rounded = round(max(0.0, min(100.0, percent)), 1)
    if abs(rounded - round(rounded)) < 1e-9:
        return f"{int(round(rounded))}%"
    return f"{rounded:.1f}%"
