"""一周后陌生展品独立作答的逐人核对。

收卷状态分类（与需求逐条对应）：
- ``valid_gallery``：第 7–10 个自然日、馆内独立完成的迁移作答，零分同样有效
- ``valid_home``：窗口内、独立但在家完成，属另一回收途径，不计主结果
- ``process_noncompliant``：窗口内但独立性无法确认（unknown）等过程不合规
- ``out_of_window``：窗口外作答（含第 6 日提前回收、第 11 日之后迟到卷）
- ``window_open_no_paper``：截至核对日收卷期（第 10 日）尚未结束且没有合条件卷
- ``no_paper_at_close``：收卷期满仍无卷
- ``exited``：开课时到课后退出（left），单独保留在分母、单列保护指标
- ``repeat_visitor``：重复到访，保留在到访团留档、不进分母
- ``absent``：未到课，不入组
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass

from .loader import TrialData, AnswerRecord, TRANSFER_WINDOW_DAYS
from .enrollment import build_enrollment

VALID_GALLERY = "valid_gallery"
VALID_HOME = "valid_home"
PROCESS_NONCOMPLIANT = "process_noncompliant"
OUT_OF_WINDOW = "out_of_window"
WINDOW_OPEN_NO_PAPER = "window_open_no_paper"
NO_PAPER_AT_CLOSE = "no_paper_at_close"
EXITED = "exited"
REPEAT_VISITOR = "repeat_visitor"
ABSENT = "absent"

# 计入主结果的状态
PRIMARY_STATUSES = {VALID_GALLERY}
# 已走满收卷期、可判定为缺测的状态
MISSING_STATUSES = {NO_PAPER_AT_CLOSE, OUT_OF_WINDOW, PROCESS_NONCOMPLIANT}
# 截至核对日仍不能判定的状态
PENDING_STATUSES = {WINDOW_OPEN_NO_PAPER}


@dataclass(frozen=True)
class ChildOutcome:
    class_id: str
    child: str
    assigned: str
    actual: str
    pair: str
    status: str
    score_ratio: float | None
    answer_id: str | None
    answer_day: _dt.date | None
    detail: str


def transfer_window_end(data: TrialData, class_id: str) -> _dt.date:
    start = data.class_day(class_id)
    return start + _dt.timedelta(days=TRANSFER_WINDOW_DAYS[1])


def _classify_answer(
    data: TrialData, answer: AnswerRecord
) -> tuple[str, str]:
    offset = (answer.day - data.class_day(answer.class_id)).days
    low, high = TRANSFER_WINDOW_DAYS
    if not low <= offset <= high:
        return OUT_OF_WINDOW, f"作答在第 {offset} 日，超出第 {low}–{high} 日窗口"
    if answer.independent != "yes":
        return PROCESS_NONCOMPLIANT, f"独立性记录为 {answer.independent}，过程不合规"
    if answer.setting == "gallery":
        return VALID_GALLERY, "窗口内馆内独立作答"
    if answer.setting == "home":
        return VALID_HOME, "窗口内独立但在家完成，属另一回收途径"
    return PROCESS_NONCOMPLIANT, f"场景 {answer.setting} 不满足主结果条件"


def reconcile(
    data: TrialData, anchor_day: _dt.date
) -> list[ChildOutcome]:
    """以核对日 ``anchor_day`` 对名册逐人判定主结果回收状态。"""
    enrollment = build_enrollment(data)
    transfer_rows: dict[tuple[str, str], list[AnswerRecord]] = {}
    for answer in data.answers:
        # 连续更新快照：核对日之后才出现的答卷当时尚未回收，不参与判定
        if answer.source == "transfer" and answer.day <= anchor_day:
            transfer_rows.setdefault((answer.class_id, answer.child), []).append(answer)

    outcomes: list[ChildOutcome] = []
    for (class_id, child), item in enrollment.items():
        klass = data.class_by_id[class_id]
        base = dict(
            class_id=class_id,
            child=child,
            assigned=item.assigned,
            actual=item.actual,
            pair=klass.pair,
        )
        if item.repeat_visitor:
            outcomes.append(ChildOutcome(
                **base, status=REPEAT_VISITOR, score_ratio=None,
                answer_id=None, answer_day=None,
                detail="重复到访，按首次符合资格团保留分派，本团仅作暴露留档",
            ))
            continue
        if not item.attended:
            outcomes.append(ChildOutcome(
                **base, status=ABSENT, score_ratio=None,
                answer_id=None, answer_day=None, detail="未到课，不入 ITT 分母",
            ))
            continue
        if item.exited:
            outcomes.append(ChildOutcome(
                **base, status=EXITED, score_ratio=None,
                answer_id=None, answer_day=None,
                detail="开课后退出，保留在原分派分母并计入保护指标",
            ))
            continue

        rows = transfer_rows.get((class_id, child), [])
        window_end = transfer_window_end(data, class_id)
        if not rows:
            if anchor_day < window_end:
                status, detail = (
                    WINDOW_OPEN_NO_PAPER,
                    f"收卷期 {window_end} 未结束，暂不能判定缺测",
                )
            else:
                status, detail = (
                    NO_PAPER_AT_CLOSE,
                    f"收卷期 {window_end} 已满，无迁移卷",
                )
            outcomes.append(ChildOutcome(
                **base, status=status, score_ratio=None,
                answer_id=None, answer_day=None, detail=detail,
            ))
            continue

        classified = [
            (_classify_answer(data, answer), answer) for answer in rows
        ]
        # 多条记录时优先采用合条件的馆内独立卷，其余状态在 detail 中留痕
        ranked = (VALID_GALLERY, VALID_HOME, PROCESS_NONCOMPLIANT, OUT_OF_WINDOW)
        chosen = min(classified, key=lambda pair: ranked.index(pair[0][0]))
        (status, detail), answer = chosen
        # 收卷期未走满时，提前卷等不合条件记录仍可能被后续合条件卷替代，
        # 此时保持 pending，不提前判缺测
        if anchor_day < window_end and status not in (VALID_GALLERY, VALID_HOME):
            status = WINDOW_OPEN_NO_PAPER
            detail = (
                f"收卷期 {window_end} 未结束；现有记录 {answer.answer_id} "
                f"暂不合条件（{detail}），等待窗口内合条件卷"
            )
            answer = None
        if answer is not None and len(classified) > 1:
            others = "; ".join(
                f"{a.answer_id}:{st}" for (st, _), a in classified if a is not answer
            )
            detail = f"{detail}；另有记录 {others}"
        outcomes.append(ChildOutcome(
            **base,
            status=status,
            score_ratio=answer.score_ratio if answer is not None and status in PRIMARY_STATUSES else None,
            answer_id=answer.answer_id if answer is not None else None,
            answer_day=answer.day if answer is not None else None,
            detail=detail,
        ))
    return outcomes


def secondary_answer_counts(data: TrialData) -> dict[str, int]:
    """即时席间练习与在家完成答案分别计数，不进入主结果。"""
    counts = {"practice": 0, "transfer_home": 0}
    for answer in data.answers:
        if answer.source == "practice":
            counts["practice"] += 1
        elif answer.setting == "home":
            counts["transfer_home"] += 1
    return counts
