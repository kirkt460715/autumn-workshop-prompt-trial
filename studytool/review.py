"""复看决定点：按 review_plan 登记的时点与阈值给出采用判定。

正式复看（formal）必须同时满足：
1. 成熟且 ITT 可估计的区组数达到 min_pairs；
2. 配对平均增益下界不低于 gain_floor（以满分比例差计）；
3. 两臂缺测率差不超过 missing_gap_ceiling；
4. 2–3 年级负担率不超过 burden_ceiling。
探索复看（exploratory）只汇总所用结果与时点、列出候选区组与点估计，
不产生采用决定；单场回卷早不构成采用依据。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .loader import TrialData, ReviewRecord
from .analysis import (
    primary_aggregate,
    conditional_aggregate,
    pair_results,
    AggregateResult,
)
from .contamination import assess_pairs, ITT_ESTIMABLE


@dataclass
class ReviewDecision:
    review: ReviewRecord
    anchor_day: str
    decision: str  # adopt / hold / exploratory_only / insufficient
    checks: dict[str, dict[str, object]]
    primary: AggregateResult
    conditional: AggregateResult
    mature_pairs: list[str]
    notes: list[str] = field(default_factory=list)

    @property
    def can_adopt(self) -> bool:
        return self.decision == "adopt"


def evaluate_review(data: TrialData, review: ReviewRecord) -> ReviewDecision:
    anchor = review.day
    results = pair_results(data, anchor)
    assessments = assess_pairs(data)
    mature = sorted(p for p, r in results.items() if r.mature)
    primary = primary_aggregate(data, anchor, target=review.target)
    conditional = conditional_aggregate(data, anchor, target=review.target)

    notes: list[str] = []
    if review.use == "exploratory":
        notes.append("探索复看只登记所用结果与时点，不作采用判定")
        return ReviewDecision(
            review=review,
            anchor_day=anchor.isoformat(),
            decision="exploratory_only",
            checks={},
            primary=primary,
            conditional=conditional,
            mature_pairs=mature,
            notes=notes,
        )

    checks: dict[str, dict[str, object]] = {}
    checks["min_pairs"] = {
        "observed": primary.pair_count,
        "threshold": review.min_pairs,
        "pass": primary.pair_count >= review.min_pairs,
        "detail": "仅统计成熟且 ITT 可估计、符合复看目标的区组",
    }

    gain_pass = (
        primary.ci_low is not None
        and primary.ci_low == primary.ci_low  # 排除 NaN
        and primary.ci_low >= review.gain_floor
    )
    checks["gain_floor"] = {
        "mean_gain": primary.mean_gain,
        "ci_low": primary.ci_low,
        "ci_high": primary.ci_high,
        "threshold": review.gain_floor,
        "pass": bool(gain_pass),
        "detail": "配对区组 hint-control 平均增益的双侧 95% 置信区间下界",
    }

    missing_gap = primary.missing_gap_max
    missing_pass = missing_gap is not None and missing_gap <= review.missing_gap_ceiling
    checks["missing_gap"] = {
        "observed": missing_gap,
        "threshold": review.missing_gap_ceiling,
        "pass": bool(missing_pass),
        "detail": "区内两臂缺测率差的最大值；收卷期未结束的 pending 不计缺测",
    }

    burden_pass = (
        primary.burden_max is not None
        and primary.burden_max == primary.burden_max
        and primary.burden_max <= review.burden_ceiling
    )
    checks["burden"] = {
        "observed": primary.burden_max,
        "control": primary.burden_control,
        "hint": primary.burden_hint,
        "threshold": review.burden_ceiling,
        "pass": bool(burden_pass),
        "detail": "开课时 2–3 年级限时未完成或退出比例",
    }

    all_pass = all(item["pass"] for item in checks.values())
    decision = "adopt" if all_pass else "hold"
    if not all_pass:
        failed = [name for name, item in checks.items() if not item["pass"]]
        notes.append("未达到正式复看条件：" + "、".join(failed))
    clean_mature = [
        p for p in mature if assessments[p].status == ITT_ESTIMABLE
    ]
    notes.append(
        f"成熟区组 {len(mature)} 个，其中 ITT 可估计 {len(clean_mature)} 个；"
        "单场回卷早不单独决定采用"
    )
    return ReviewDecision(
        review=review,
        anchor_day=anchor.isoformat(),
        decision=decision,
        checks=checks,
        primary=primary,
        conditional=conditional,
        mature_pairs=mature,
        notes=notes,
    )


def evaluate_all(data: TrialData) -> list[ReviewDecision]:
    return [evaluate_review(data, review) for review in data.reviews]
