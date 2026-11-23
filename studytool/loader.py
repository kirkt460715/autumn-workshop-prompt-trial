"""CSV 读取与语义核验。所有日期统一转为 ``datetime.date``。"""
from __future__ import annotations

import csv
import datetime as _dt
from dataclasses import dataclass, field
from pathlib import Path

TABLES = {
    "classes": "class_id pair school day assigned actual teacher group_type".split(),
    "children": "class_id child family grade attendance overtime".split(),
    "answers": (
        "answer_id class_id child day source setting raw_score max_score independent"
    ).split(),
    "contacts": "contact source_class target_class day kind content".split(),
    "review_plan": (
        "review day use target gain_floor missing_gap_ceiling burden_ceiling min_pairs"
    ).split(),
    "next_classes": (
        "candidate day school grade teacher block prior_material state paired_with "
        "followup_slot"
    ).split(),
}

ASSIGNED_ARMS = {"control", "hint"}
ATTENDANCE = {"present", "left", "absent"}
ANSWER_SOURCES = {"practice", "transfer"}
SETTINGS = {"room", "gallery", "home"}
INDEPENDENCE = {"yes", "no", "unknown"}
CONTACT_KINDS = {"teacher", "family", "pupil"}
REVIEW_USES = {"formal", "exploratory"}
CANDIDATE_STATES = {"proposed", "hold_control", "teacher_updated"}
YES_NO = {"yes", "no"}

# 只介绍场馆、不含提示做法或迁移题的接触不构成方法暴露
NON_TRANSMITTING_CONTENT = {"仅场馆介绍"}
TRANSFER_WINDOW_DAYS = (7, 10)


def parse_day(value: str) -> _dt.date:
    return _dt.date.fromisoformat(value)


@dataclass
class ClassRecord:
    class_id: str
    pair: str
    school: str
    day: _dt.date
    assigned: str
    actual: str
    teacher: str
    group_type: str


@dataclass
class ChildRecord:
    class_id: str
    child: str
    family: str
    grade: int
    attendance: str
    overtime: bool
    repeat_visitor: bool


@dataclass
class AnswerRecord:
    answer_id: str
    class_id: str
    child: str
    day: _dt.date
    source: str
    setting: str
    raw_score: int
    max_score: int
    independent: str

    @property
    def score_ratio(self) -> float:
        return self.raw_score / self.max_score


@dataclass
class ContactRecord:
    contact: str
    source_class: str
    target_class: str
    day: _dt.date
    kind: str
    content: str

    @property
    def transmitting(self) -> bool:
        return self.content not in NON_TRANSMITTING_CONTENT


@dataclass
class ReviewRecord:
    review: str
    day: _dt.date
    use: str
    target: str
    gain_floor: float
    missing_gap_ceiling: float
    burden_ceiling: float
    min_pairs: int


@dataclass
class CandidateRecord:
    candidate: str
    day: _dt.date
    school: str
    grade: int
    teacher: str
    block: str
    prior_material: bool
    state: str
    paired_with: str
    followup_slot: str | None


@dataclass
class TrialData:
    classes: list[ClassRecord]
    children: list[ChildRecord]
    answers: list[AnswerRecord]
    contacts: list[ContactRecord]
    reviews: list[ReviewRecord]
    candidates: list[CandidateRecord]
    class_by_id: dict[str, ClassRecord] = field(default_factory=dict)
    pair_classes: dict[str, dict[str, ClassRecord]] = field(default_factory=dict)
    children_by_class: dict[str, list[ChildRecord]] = field(default_factory=dict)

    def class_day(self, class_id: str) -> _dt.date:
        return self.class_by_id[class_id].day


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError(f"{path} 缺少表头")
        if reader.fieldnames != TABLES[path.stem]:
            raise ValueError(
                f"{path.name} 表头与约定不符：{reader.fieldnames} != {TABLES[path.stem]}"
            )
        rows = list(reader)
    if not rows:
        raise ValueError(f"{path.name} 为空")
    for row in rows:
        if any(value is None for value in row.values()):
            raise ValueError(f"{path.name} 存在多余列或错位行：{row}")
    return rows


def _check_unique(rows: list[dict[str, str]], key: tuple[str, ...], table: str) -> None:
    seen = set()
    for row in rows:
        value = tuple(row[k] for k in key)
        if not all(value):
            raise ValueError(f"{table} 存在空记录键 {key}：{row}")
        if value in seen:
            raise ValueError(f"{table} 记录键重复：{value}")
        seen.add(value)


def _check_ratio(rows: list[dict[str, str]], columns: tuple[str, ...], table: str) -> None:
    for row in rows:
        for column in columns:
            try:
                value = float(row[column])
            except ValueError as exc:
                raise ValueError(f"{table}.{column} 不是数值：{row[column]}") from exc
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{table}.{column} 超出 0 到 1 范围：{row}")


def load_trial(data_dir: str | Path) -> TrialData:
    """读取六张表并完成字段域、键值、关联与计分规则核验。"""
    data_dir = Path(data_dir)
    raw = {name: _read_rows(data_dir / f"{name}.csv") for name in TABLES}

    _check_unique(raw["classes"], ("class_id",), "classes")
    _check_unique(raw["children"], ("class_id", "child"), "children")
    _check_unique(raw["answers"], ("answer_id",), "answers")
    _check_unique(raw["contacts"], ("contact",), "contacts")
    _check_unique(raw["review_plan"], ("review",), "review_plan")
    _check_unique(raw["next_classes"], ("candidate",), "next_classes")

    classes = [
        ClassRecord(
            r["class_id"], r["pair"], r["school"], parse_day(r["day"]),
            r["assigned"], r["actual"], r["teacher"], r["group_type"],
        )
        for r in raw["classes"]
    ]
    for record in classes:
        if record.assigned not in ASSIGNED_ARMS or record.actual not in ASSIGNED_ARMS:
            raise ValueError(f"classes 臂值非法：{record}")

    pair_classes: dict[str, dict[str, ClassRecord]] = {}
    for record in classes:
        arms = pair_classes.setdefault(record.pair, {})
        if record.assigned in arms:
            raise ValueError(f"区组 {record.pair} 中 {record.assigned} 臂重复")
        arms[record.assigned] = record
    for pair, arms in pair_classes.items():
        if set(arms) != ASSIGNED_ARMS:
            raise ValueError(f"区组 {pair} 未同时包含 control 与 hint")

    class_ids = {r.class_id for r in classes}
    children: list[ChildRecord] = []
    for r in raw["children"]:
        if r["class_id"] not in class_ids:
            raise ValueError(f"children 引用了不存在的 class_id：{r}")
        if r["attendance"] not in ATTENDANCE:
            raise ValueError(f"children.attendance 非法：{r}")
        if r["overtime"] not in YES_NO:
            raise ValueError(f"children.overtime 非法：{r}")
        grade = int(r["grade"])
        if not 1 <= grade <= 9:
            raise ValueError(f"children.grade 超出合理范围：{r}")
        children.append(
            ChildRecord(
                r["class_id"], r["child"], r["family"], grade,
                r["attendance"], r["overtime"] == "yes", r["child"] == "H-repeat",
            )
        )

    answers: list[AnswerRecord] = []
    answer_keys: set[tuple[str, str, str]] = set()
    for r in raw["answers"]:
        if r["class_id"] not in class_ids:
            raise ValueError(f"answers 引用了不存在的 class_id：{r}")
        if (r["class_id"], r["child"]) not in {(c.class_id, c.child) for c in children}:
            raise ValueError(f"answers 找不到对应报名名册记录：{r['answer_id']}")
        if r["source"] not in ANSWER_SOURCES or r["setting"] not in SETTINGS:
            raise ValueError(f"answers 来源或场景非法：{r}")
        if r["independent"] not in INDEPENDENCE:
            raise ValueError(f"answers.independent 非法：{r}")
        raw_score = int(r["raw_score"])
        max_score = int(r["max_score"])
        if max_score <= 0 or not 0 <= raw_score <= max_score:
            raise ValueError(f"answers 计分越界：{r}")
        dedup_key = (r["class_id"], r["child"], r["source"])
        if dedup_key in answer_keys:
            raise ValueError(f"同一孩子同一来源出现多条记录：{r['answer_id']}")
        answer_keys.add(dedup_key)
        answers.append(
            AnswerRecord(
                r["answer_id"], r["class_id"], r["child"], parse_day(r["day"]),
                r["source"], r["setting"], raw_score, max_score, r["independent"],
            )
        )

    contacts: list[ContactRecord] = []
    for r in raw["contacts"]:
        for endpoint in (r["source_class"], r["target_class"]):
            if endpoint not in class_ids:
                raise ValueError(f"contacts 引用了不存在的 class_id：{r}")
        if r["kind"] not in CONTACT_KINDS:
            raise ValueError(f"contacts.kind 非法：{r}")
        contacts.append(
            ContactRecord(
                r["contact"], r["source_class"], r["target_class"], parse_day(r["day"]),
                r["kind"], r["content"],
            )
        )

    _check_ratio(raw["review_plan"], ("gain_floor", "missing_gap_ceiling", "burden_ceiling"),
                 "review_plan")
    reviews: list[ReviewRecord] = []
    for r in raw["review_plan"]:
        if r["use"] not in REVIEW_USES:
            raise ValueError(f"review_plan.use 非法：{r}")
        if r["target"] not in {"all", "school", "open"}:
            raise ValueError(f"review_plan.target 非法：{r}")
        reviews.append(
            ReviewRecord(
                r["review"], parse_day(r["day"]), r["use"], r["target"],
                float(r["gain_floor"]), float(r["missing_gap_ceiling"]),
                float(r["burden_ceiling"]), int(r["min_pairs"]),
            )
        )

    candidates: list[CandidateRecord] = []
    candidate_ids = {r["candidate"] for r in raw["next_classes"]}
    for r in raw["next_classes"]:
        if r["state"] not in CANDIDATE_STATES:
            raise ValueError(f"next_classes.state 非法：{r}")
        if r["prior_material"] not in YES_NO:
            raise ValueError(f"next_classes.prior_material 非法：{r}")
        paired = r["paired_with"]
        if paired and paired not in candidate_ids:
            raise ValueError(f"next_classes.paired_with 指向不存在的候选：{r}")
        slot = r["followup_slot"] or None
        candidates.append(
            CandidateRecord(
                r["candidate"], parse_day(r["day"]), r["school"], int(r["grade"]),
                r["teacher"], r["block"], r["prior_material"] == "yes", r["state"],
                paired, slot,
            )
        )

    children_by_class: dict[str, list[ChildRecord]] = {}
    for record in children:
        children_by_class.setdefault(record.class_id, []).append(record)

    return TrialData(
        classes=classes,
        children=children,
        answers=answers,
        contacts=contacts,
        reviews=sorted(reviews, key=lambda r: r.day),
        candidates=candidates,
        class_by_id={r.class_id: r for r in classes},
        pair_classes=pair_classes,
        children_by_class=children_by_class,
    )
