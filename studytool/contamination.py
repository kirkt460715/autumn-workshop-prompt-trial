"""时序交流资料与团群可估计性分级。

分级口径：
- ``itt_estimable``：区内两臂实际授课与指派一致，且在收卷期内没有任何
  传递提示做法或迁移题的交流边连入团内任一团。随机比较仍估计指派效果（ITT）。
- ``exposure_conditional``：授课保持两臂对照，但存在区内交流（含换班接触、
  家长拿到完整迁移题、跨团重复到访），只支持“有交流条件下”的结果。
- ``unidentifiable``：对照臂实际收到提示等原因使两臂不再形成方法对照，
  随机比较无法区分两种提示。

只介绍场馆（``仅场馆介绍``）的接触不构成方法暴露，保留留痕但不改变分级。
传递边按目标团收卷期（第 0–10 个自然日）判定时点；收卷期结束后的接触
不影响本轮主结果，标记为 ``late``。
"""
from __future__ import annotations

from dataclasses import dataclass

from .loader import TrialData, ContactRecord, ClassRecord, TRANSFER_WINDOW_DAYS

ITT_ESTIMABLE = "itt_estimable"
EXPOSURE_CONDITIONAL = "exposure_conditional"
UNIDENTIFIABLE = "unidentifiable"

TIMELY = "timely"
LATE = "late"
NON_TRANSMITTING = "non_transmitting"


@dataclass
class PairAssessment:
    pair: str
    control: ClassRecord
    hint: ClassRecord
    status: str
    reasons: list[str]
    component_id: str | None
    component_members: frozenset[str]
    delivery_deviation: bool


def timing_for(data: TrialData, contact: ContactRecord) -> str:
    """接触相对目标团授课日的时点分类（证据日以 contacts.day 为准）。"""
    if not contact.transmitting:
        return NON_TRANSMITTING
    target_day = data.class_day(contact.target_class)
    offset = (contact.day - target_day).days
    if 0 <= offset <= TRANSFER_WINDOW_DAYS[1]:
        return TIMELY
    return LATE


def build_components(
    data: TrialData,
) -> tuple[dict[str, frozenset[str]], dict[str, list[ContactRecord]], dict[str, str]]:
    """返回：团 -> 交流团群成员、团 -> 团上的接触、接触 -> 时点分类。"""
    parent = {c.class_id: c.class_id for c in data.classes}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        root_a, root_b = find(a), find(b)
        if root_b != root_a:
            parent[root_b] = root_a

    timing: dict[str, str] = {}
    class_contacts: dict[str, list[ContactRecord]] = {
        c.class_id: [] for c in data.classes
    }
    for contact in data.contacts:
        timing[contact.contact] = timing_for(data, contact)
        class_contacts[contact.source_class].append(contact)
        class_contacts[contact.target_class].append(contact)
        if timing[contact.contact] == TIMELY:
            union(contact.source_class, contact.target_class)

    groups: dict[str, list[str]] = {}
    for class_id in parent:
        groups.setdefault(find(class_id), []).append(class_id)
    component_of: dict[str, frozenset[str]] = {}
    for members in groups.values():
        members_frozen = frozenset(members)
        for class_id in members:
            component_of[class_id] = members_frozen
    return component_of, class_contacts, timing


def assess_pairs(data: TrialData) -> dict[str, PairAssessment]:
    component_of, class_contacts, timing = build_components(data)
    assessments: dict[str, PairAssessment] = {}

    for pair, arms in sorted(data.pair_classes.items()):
        control, hint = arms["control"], arms["hint"]
        member_ids = {control.class_id, hint.class_id}
        reasons: list[str] = []
        delivery_deviation = False

        for klass in (control, hint):
            if klass.actual != klass.assigned:
                delivery_deviation = True
                reasons.append(
                    f"{klass.class_id} 指派 {klass.assigned} 但实际授课 {klass.actual}"
                )

        touching: list[ContactRecord] = []
        for class_id in member_ids:
            for contact in class_contacts[class_id]:
                if timing[contact.contact] == TIMELY and contact not in touching:
                    touching.append(contact)
        for contact in sorted(touching, key=lambda c: c.contact):
            other = (
                contact.target_class
                if contact.source_class in member_ids
                else contact.source_class
            )
            reasons.append(
                f"{contact.contact} {contact.kind} 接触（{contact.content}）："
                f"{contact.source_class}→{contact.target_class}，"
                f"证据日 {contact.day}，连到团 {other}"
            )

        both_hint = control.actual == "hint" and hint.actual == "hint"
        if both_hint:
            status = UNIDENTIFIABLE
            reasons.append("两臂实际均为 hint，不再存在提示方式对照，随机比较无法区分")
        elif delivery_deviation:
            # 一臂换班但两臂仍形成对照时，只能支持有交流条件下的结果
            status = EXPOSURE_CONDITIONAL
        elif touching:
            status = EXPOSURE_CONDITIONAL
        else:
            status = ITT_ESTIMABLE

        component_members = component_of[control.class_id]
        component_id = None
        if status != ITT_ESTIMABLE:
            component_id = "C-" + min(component_members)

        assessments[pair] = PairAssessment(
            pair=pair,
            control=control,
            hint=hint,
            status=status,
            reasons=reasons,
            component_id=component_id,
            component_members=component_members if component_id else frozenset(),
            delivery_deviation=delivery_deviation,
        )
    return assessments


def exposure_table(data: TrialData) -> list[dict[str, str]]:
    """供排课/报告使用的逐条接触时点表。"""
    _, _, timing = build_components(data)
    return [
        {
            "contact": contact.contact,
            "source_class": contact.source_class,
            "target_class": contact.target_class,
            "day": contact.day.isoformat(),
            "kind": contact.kind,
            "content": contact.content,
            "timing": timing[contact.contact],
        }
        for contact in data.contacts
    ]
