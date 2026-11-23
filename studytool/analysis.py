"""配对区组效果、缺测范围与低龄负担分析（标准库实现）。"""
from __future__ import annotations

import datetime as _dt
import math
import statistics
from dataclasses import dataclass, field

from .loader import TrialData
from .reconciliation import (
    reconcile,
    ChildOutcome,
    PRIMARY_STATUSES,
    MISSING_STATUSES,
    PENDING_STATUSES,
    EXITED,
    VALID_HOME,
)
from .contamination import (
    assess_pairs,
    ITT_ESTIMABLE,
    EXPOSURE_CONDITIONAL,
    UNIDENTIFIABLE,
)
from .enrollment import itt_denominator

# 常见自由度对应的双侧 95% t 分位数，避免引入第三方统计库
_T_CRIT_95 = {
    1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571,
    6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228,
    11: 2.201, 12: 2.179, 13: 2.160, 14: 2.145, 15: 2.131,
    16: 2.120, 17: 2.110, 18: 2.101, 19: 2.093, 20: 2.086,
    21: 2.080, 22: 2.074, 23: 2.069, 24: 2.064, 25: 2.060,
    29: 2.045, 30: 2.042,
}
BURDEN_GRADES = {2, 3}


def t_critical_95(df: int) -> float:
    if df <= 0:
        return float("nan")
    if df in _T_CRIT_95:
        return _T_CRIT_95[df]
    if df > 30:
        return 1.96
    # 表内空档线性插值
    keys = sorted(_T_CRIT_95)
    for low, high in zip(keys, keys[1:]):
        if low < df < high:
            ratio = (df - low) / (high - low)
            return _T_CRIT_95[low] * (1 - ratio) + _T_CRIT_95[high] * ratio
    return 1.96


@dataclass
class ArmSummary:
    class_id: str
    assigned: str
    denominator: int
    observed: int
    missing: int
    pending: int
    exited: int
    other_channel: int
    missing_rate: float
    pending_rate: float
    mean_score: float | None


@dataclass
class PairResult:
    pair: str
    status: str
    component_id: str | None
    mature: bool
    control: ArmSummary
    hint: ArmSummary
    gain: float | None
    missing_gap: float | None
    reasons: list[str] = field(default_factory=list)


@dataclass
class AggregateResult:
    label: str
    pair_count: int
    mean_gain: float | None
    ci_low: float | None
    ci_high: float | None
    gains: dict[str, float]
    missing_gap_max: float | None
    burden_control: float | None
    burden_hint: float | None
    burden_max: float | None
    included_pairs: list[str]
    excluded_pairs: dict[str, str]


def _is_mature(data: TrialData, pair: str, anchor_day: _dt.date) -> bool:
    arms = data.pair_classes[pair]
    earliest = min(klass.day for klass in arms.values())
    return anchor_day >= earliest + _dt.timedelta(days=10)


def summarize_class(
    data: TrialData, class_id: str, outcomes: list[ChildOutcome]
) -> ArmSummary:
    rows = [o for o in outcomes if o.class_id == class_id]
    denominator_items = itt_denominator(data, class_id)
    denominator = len(denominator_items)
    observed = sum(o.status in PRIMARY_STATUSES for o in rows)
    missing = sum(o.status in MISSING_STATUSES for o in rows)
    pending = sum(o.status in PENDING_STATUSES for o in rows)
    exited = sum(o.status == EXITED for o in rows)
    other_channel = sum(o.status == VALID_HOME for o in rows)
    scores = [o.score_ratio for o in rows if o.status in PRIMARY_STATUSES]
    return ArmSummary(
        class_id=class_id,
        assigned=data.class_by_id[class_id].assigned,
        denominator=denominator,
        observed=observed,
        missing=missing,
        pending=pending,
        exited=exited,
        other_channel=other_channel,
        missing_rate=missing / denominator if denominator else float("nan"),
        pending_rate=pending / denominator if denominator else float("nan"),
        mean_score=statistics.mean(scores) if scores else None,
    )


def pair_results(
    data: TrialData, anchor_day: _dt.date
) -> dict[str, PairResult]:
    outcomes = reconcile(data, anchor_day)
    assessments = assess_pairs(data)
    results: dict[str, PairResult] = {}
    for pair, assessment in assessments.items():
        control = summarize_class(data, assessment.control.class_id, outcomes)
        hint = summarize_class(data, assessment.hint.class_id, outcomes)
        mature = _is_mature(data, pair, anchor_day)
        if control.mean_score is not None and hint.mean_score is not None:
            gain = hint.mean_score - control.mean_score
        else:
            gain = None
        missing_gap = abs(hint.missing_rate - control.missing_rate)
        results[pair] = PairResult(
            pair=pair,
            status=assessment.status,
            component_id=assessment.component_id,
            mature=mature,
            control=control,
            hint=hint,
            gain=gain,
            missing_gap=missing_gap,
            reasons=assessment.reasons,
        )
    return results


def _paired_ci(gains: list[float]) -> tuple[float, float, float]:
    mean_gain = statistics.mean(gains)
    if len(gains) < 2:
        return mean_gain, float("nan"), float("nan")
    sd = statistics.stdev(gains)
    se = sd / math.sqrt(len(gains))
    crit = t_critical_95(len(gains) - 1)
    return mean_gain, mean_gain - crit * se, mean_gain + crit * se


def burden_rates(data: TrialData, pair_filter: set[str] | None = None) -> dict[str, float]:
    """开课时 2–3 年级孩子的限时未完成（overtime）或退出占比，按原分派臂统计。"""
    totals = {"control": 0, "hint": 0}
    burden = {"control": 0, "hint": 0}
    for record in data.children:
        if record.grade not in BURDEN_GRADES or record.attendance == "absent":
            continue
        klass = data.class_by_id[record.class_id]
        if pair_filter is not None and klass.pair not in pair_filter:
            continue
        arm = klass.assigned
        totals[arm] += 1
        if record.overtime or record.attendance == "left":
            burden[arm] += 1
    rates = {
        arm: (burden[arm] / totals[arm] if totals[arm] else float("nan"))
        for arm in totals
    }
    rates["max"] = max(rates["control"], rates["hint"])
    return rates


def aggregate(
    data: TrialData,
    anchor_day: _dt.date,
    include_statuses: set[str],
    target: str = "all",
    label: str = "主结果",
) -> AggregateResult:
    results = pair_results(data, anchor_day)
    included: list[str] = []
    excluded: dict[str, str] = {}
    gains: dict[str, float] = {}
    missing_gaps: list[float] = []

    for pair, result in results.items():
        klass = data.pair_classes[pair]["control"]
        if target == "school" and klass.group_type != "school":
            excluded[pair] = "复看目标仅限 school 区组"
            continue
        if not result.mature:
            excluded[pair] = "收卷期未走满，区组未成熟"
            continue
        if result.status not in include_statuses:
            excluded[pair] = f"可估计性分级 {result.status} 不在本次证据集"
            continue
        if result.gain is None:
            excluded[pair] = "臂内无有效主结果，无法计算区组差值"
            continue
        included.append(pair)
        gains[pair] = result.gain
        if result.missing_gap is not None:
            missing_gaps.append(result.missing_gap)

    ordered = [gains[p] for p in included]
    if ordered:
        mean_gain, ci_low, ci_high = _paired_ci(ordered)
    else:
        mean_gain = ci_low = ci_high = None
    burden = burden_rates(data, set(included))
    return AggregateResult(
        label=label,
        pair_count=len(included),
        mean_gain=mean_gain,
        ci_low=ci_low,
        ci_high=ci_high,
        gains=gains,
        missing_gap_max=max(missing_gaps) if missing_gaps else None,
        burden_control=burden["control"],
        burden_hint=burden["hint"],
        burden_max=burden["max"],
        included_pairs=included,
        excluded_pairs=excluded,
    )


def primary_aggregate(data: TrialData, anchor_day: _dt.date, target: str = "all") -> AggregateResult:
    """采用证据只使用成熟且 ITT 可估计的区组。"""
    return aggregate(
        data, anchor_day, include_statuses={ITT_ESTIMABLE},
        target=target, label="ITT 可估计区组",
    )


def conditional_aggregate(data: TrialData, anchor_day: _dt.date, target: str = "all") -> AggregateResult:
    """受交流团群的有交流条件结果，单独报告、不进入采用证据。"""
    return aggregate(
        data, anchor_day, include_statuses={EXPOSURE_CONDITIONAL},
        target=target, label="有交流条件区组",
    )


def status_counts() -> dict[str, str]:
    return {
        "itt_estimable": ITT_ESTIMABLE,
        "exposure_conditional": EXPOSURE_CONDITIONAL,
        "unidentifiable": UNIDENTIFIABLE,
    }
