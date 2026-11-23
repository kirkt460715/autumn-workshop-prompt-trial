"""报名名册、重复到访与 ITT 分母。

规则（见 data-contract.md）：
- 每个孩子按首次符合资格的团保留随机分派；重复到访（名册中的 ``H-repeat`` 行）
  不进入到访团的分母，其后一段经历仅用于判断暴露。
- 出勤（present）与开课后退出（left）的孩子都保留在原分派分母；
  未到课（absent）的孩子没有进入试验，不计入分母。
"""
from __future__ import annotations

from dataclasses import dataclass

from .loader import TrialData, ChildRecord, ClassRecord


@dataclass(frozen=True)
class Enrollment:
    class_id: str
    child: str
    family: str
    grade: int
    assigned: str
    actual: str
    attended: bool
    exited: bool
    overtime: bool
    repeat_visitor: bool


def build_enrollment(data: TrialData) -> dict[tuple[str, str], Enrollment]:
    """按团返回名册上每名孩子的入组信息（含重复到访标记）。"""
    enrollment: dict[tuple[str, str], Enrollment] = {}
    for record in data.children:
        klass = data.class_by_id[record.class_id]
        enrollment[(record.class_id, record.child)] = Enrollment(
            class_id=record.class_id,
            child=record.child,
            family=record.family,
            grade=record.grade,
            assigned=klass.assigned,
            actual=klass.actual,
            attended=record.attendance in {"present", "left"},
            exited=record.attendance == "left",
            overtime=record.overtime,
            repeat_visitor=record.repeat_visitor,
        )
    return enrollment


def itt_denominator(data: TrialData, class_id: str) -> list[Enrollment]:
    """该团的 ITT 分母：到课者（含退出者），剔除重复到访与未到课者。"""
    enrollment = build_enrollment(data)
    return [
        item
        for item in enrollment.values()
        if item.class_id == class_id
        and item.attended
        and not item.repeat_visitor
    ]


def repeat_visitors(data: TrialData) -> list[ChildRecord]:
    """重复到访登记行；其作答留档但不进入到访团主结果分母。"""
    return [record for record in data.children if record.repeat_visitor]


def classes_of_pair(data: TrialData, pair: str) -> tuple[ClassRecord, ClassRecord]:
    arms = data.pair_classes[pair]
    return arms["control"], arms["hint"]
