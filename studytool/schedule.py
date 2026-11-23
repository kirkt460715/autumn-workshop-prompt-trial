"""下一轮排课：未暴露对照资格、时段冲突与候选安排比较。

未暴露对照必须同时满足：
- 候选团本身没有 prior_material（家长未拿到题）；
- 实际带班教师没有“异常提示接触”记录，即：
  * 在换班中实际带过与指派不符的 hint 团（正常按指派带 hint 团属于
    试验内分工，不视为污染对照的异常接触），或
  * 在教师类提示示范的时序传递接触中涉入；
- 已订一周后独立回访时段（followup_slot 非空）。

排课硬约束：
- 同一 block 一名教师只能带一场；
- 同一 followup_slot 只够一个团独立回访，空值表示没有已订回访时段；
- 若采用某安排会让原定未暴露对照失去一周后回访时段，该对照不能同时算作可做。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .loader import TrialData, CandidateRecord
from .contamination import build_components, NON_TRANSMITTING


@dataclass
class CandidateAssessment:
    candidate: CandidateRecord
    eligible_control: bool
    ineligible_reasons: list[str]
    followup_booked: bool
    teacher_exposure_evidence: list[str]
    pair_link: str | None
    pair_retainable_now: bool | None
    pair_retainable_if_slot_held: bool | None
    pair_blockers: list[str] = field(default_factory=list)
    slot_conditions: list[str] = field(default_factory=list)
    first_identifiability_loss: str | None = None


@dataclass
class ScheduleReport:
    exposed_teachers: dict[str, list[str]]
    candidates: list[CandidateAssessment]
    slot_demand: dict[str, list[str]]
    retainable_pairs: list[str]
    notes: list[str]


def teacher_hint_exposure(data: TrialData) -> dict[str, list[str]]:
    """教师 -> 异常提示接触证据（换班授 hint、教师提示示范边）。

    正常按指派带 hint 团不算异常接触：那是随机分派下的合法授课分工，
    否则同一批老师将永远无法承担任何对照，下一轮试验无法排课。
    """
    evidence: dict[str, list[str]] = {}
    teacher_of = {c.class_id: c.teacher for c in data.classes}

    for klass in data.classes:
        if klass.actual == "hint" and klass.assigned != "hint":
            evidence.setdefault(klass.teacher, []).append(
                f"{klass.class_id} 换班后实际授 hint（原指派 {klass.assigned}）"
            )

    _, _, timing = build_components(data)
    for contact in data.contacts:
        if contact.kind != "teacher":
            continue
        if timing[contact.contact] == NON_TRANSMITTING:
            continue
        for endpoint in (contact.source_class, contact.target_class):
            teacher = teacher_of[endpoint]
            evidence.setdefault(teacher, []).append(
                f"{contact.contact} 教师提示示范接触，涉 {endpoint}（{contact.day}）"
            )
    return dict(sorted(evidence.items()))


def _control_blockers(
    candidate: CandidateRecord,
    exposed_teachers: dict[str, list[str]],
) -> tuple[bool, list[str], list[str]]:
    reasons: list[str] = []
    teacher_evidence = exposed_teachers.get(candidate.teacher, [])
    if candidate.prior_material:
        reasons.append("prior_material=yes：家长已拿到题，不能作为未暴露对照")
    if teacher_evidence:
        reasons.append(
            f"教师 {candidate.teacher} 已有提示接触记录：{'；'.join(teacher_evidence)}"
        )
    if not candidate.followup_slot:
        reasons.append("没有已订一周后回访时段（followup_slot 为空）")
    return (not reasons), reasons, teacher_evidence


def _paired(candidate: CandidateRecord, data: TrialData) -> CandidateRecord | None:
    if not candidate.paired_with:
        return None
    return next(c for c in data.candidates if c.candidate == candidate.paired_with)


def assess_schedule(data: TrialData) -> ScheduleReport:
    exposed_teachers = teacher_hint_exposure(data)

    slot_demand: dict[str, list[str]] = {}
    for candidate in data.candidates:
        if candidate.followup_slot:
            slot_demand.setdefault(candidate.followup_slot, []).append(candidate.candidate)

    assessments: dict[str, CandidateAssessment] = {}
    notes: list[str] = []

    for candidate in data.candidates:
        eligible, reasons, teacher_evidence = _control_blockers(candidate, exposed_teachers)
        assessments[candidate.candidate] = CandidateAssessment(
            candidate=candidate,
            eligible_control=eligible,
            ineligible_reasons=reasons,
            followup_booked=bool(candidate.followup_slot),
            teacher_exposure_evidence=teacher_evidence,
            pair_link=candidate.paired_with or None,
            pair_retainable_now=None,
            pair_retainable_if_slot_held=None,
        )

    # 成对候选：必须整对保留；区分硬阻断与“预留回访时段即可解除”的条件
    seen_pairs: set[str] = set()
    retainable_now: list[str] = []
    retainable_if_held: list[str] = []
    for candidate in data.candidates:
        partner_record = _paired(candidate, data)
        if partner_record is None:
            continue
        pair_key = "~".join(sorted((candidate.candidate, partner_record.candidate)))
        if pair_key in seen_pairs:
            continue
        seen_pairs.add(pair_key)

        control = candidate if not candidate.prior_material else partner_record
        hint_side = partner_record if control is candidate else candidate
        hard_blockers: list[str] = []
        slot_conditions: list[str] = []
        first_loss: list[str] = []

        control_view = assessments[control.candidate]
        for reason in control_view.ineligible_reasons:
            if reason.startswith("没有已订一周后回访时段"):
                slot_conditions.append(f"对照 {control.candidate}：{reason}，需先订时段")
            else:
                hard_blockers.append(f"对照 {control.candidate}：{reason}")
        if not control_view.followup_booked:
            first_loss.append(
                f"对照 {control.candidate} 缺少一周后回访时段，无法验证延后迁移"
            )
        # 先发生的辨识力丧失环节：值班变动 vs 通知家长
        if any("提示接触" in r for r in control_view.ineligible_reasons):
            first_loss.insert(
                0,
                f"换班使 {control.candidate} 的教师已接触提示，对照先失去提示方式区分条件",
            )
        if any("prior_material" in r for r in control_view.ineligible_reasons):
            first_loss.append(
                f"通知家长后 {control.candidate} 已拿到题，题目区分条件先丧失"
            )

        if (
            control.day == hint_side.day
            and control.block == hint_side.block
            and control.teacher == hint_side.teacher
        ):
            hard_blockers.append(
                f"{control.candidate} 与 {hint_side.candidate} 同 block 同教师，"
                "一名教师不能同时带两场"
            )

        conflict_slots: set[str] = set()
        if control.followup_slot and control.followup_slot == hint_side.followup_slot:
            conflict_slots.add(control.followup_slot)
        for slot, users in slot_demand.items():
            if control.candidate in users and any(
                user not in {control.candidate, hint_side.candidate} for user in users
            ):
                conflict_slots.add(slot)
        for slot in sorted(conflict_slots):
            users = slot_demand[slot]
            slot_conditions.append(
                f"回访时段 {slot} 同时被 {', '.join(users)} 预订，只够一个团独立回访；"
                f"须为对照 {control.candidate} 保留 {slot} 并移出其他占用，"
                "否则确认采用的同时该对照不能算作可做"
            )

        retainable_now_flag = not hard_blockers and not slot_conditions
        retainable_if_held_flag = not hard_blockers
        for cid in (control.candidate, hint_side.candidate):
            view = assessments[cid]
            view.pair_retainable_now = retainable_now_flag
            view.pair_retainable_if_slot_held = retainable_if_held_flag
            view.pair_blockers = list(hard_blockers)
            view.slot_conditions = list(slot_conditions)
            view.first_identifiability_loss = "；".join(first_loss) if first_loss else None

        if retainable_now_flag:
            retainable_now.append(pair_key)
        elif retainable_if_held_flag:
            retainable_if_held.append(pair_key)
            notes.append(
                f"候选对 {pair_key} 对照资格成立，但须先预留回访时段："
                + "；".join(slot_conditions)
            )
        else:
            notes.append(
                f"候选对 {pair_key} 不能保留为随机比较：" + "；".join(hard_blockers)
            )

    # 无配对候选单列说明
    for candidate in data.candidates:
        if not candidate.paired_with:
            notes.append(
                f"{candidate.candidate} 无配对候选，不能单独构成对照比较"
                + ("" if candidate.followup_slot else "，且没有已订回访时段")
            )

    return ScheduleReport(
        exposed_teachers=exposed_teachers,
        candidates=[assessments[c.candidate] for c in data.candidates],
        slot_demand=slot_demand,
        retainable_pairs=sorted(retainable_now + retainable_if_held),
        notes=notes,
    )
