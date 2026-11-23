"""命令行入口：随新排课与新答卷连续更新的只读分析工具。"""
from __future__ import annotations

import argparse
import datetime as _dt
from pathlib import Path

from .loader import load_trial
from .enrollment import repeat_visitors
from .reconciliation import reconcile, secondary_answer_counts
from .contamination import assess_pairs, exposure_table
from .analysis import pair_results, primary_aggregate, conditional_aggregate
from .review import evaluate_all
from .schedule import assess_schedule

STATUS_LABEL = {
    "itt_estimable": "可估计指派效果（ITT）",
    "exposure_conditional": "仅支持有交流条件下的结果",
    "unidentifiable": "无法区分两种提示",
}
TIMING_LABEL = {
    "timely": "收卷期内的传递接触",
    "late": "收卷期结束后，不影响本轮主结果",
    "non_transmitting": "不含提示做法，不构成方法暴露",
}


def _pct(value: float | None) -> str:
    if value is None or value != value:
        return "—"
    return f"{value * 100:.1f}%"


def _signed(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:+.4f}"


def cmd_check(data, _args) -> None:
    print("资料核验通过")
    print(f"  classes={len(data.classes)} children={len(data.children)} "
          f"answers={len(data.answers)} contacts={len(data.contacts)} "
          f"reviews={len(data.reviews)} candidates={len(data.candidates)}")
    repeats = repeat_visitors(data)
    if repeats:
        print("  重复到访（不进入到访团分母）：")
        for item in repeats:
            print(f"    {item.child} 到访 {item.class_id}（家庭 {item.family}）")


def cmd_pairs(data, args) -> None:
    assessments = assess_pairs(data)
    for pair, item in assessments.items():
        print(f"{pair}  [{STATUS_LABEL[item.status]}]  团群={item.component_id or '—'}")
        print(f"    control={item.control.class_id}（实际 {item.control.actual}，"
              f"师 {item.control.teacher}）  hint={item.hint.class_id}"
              f"（实际 {item.hint.actual}，师 {item.hint.teacher}）")
        if args.verbose:
            for reason in item.reasons:
                print(f"    - {reason}")
            if item.component_members:
                print(f"    交流团群成员：{', '.join(sorted(item.component_members))}")


def cmd_contacts(data, _args) -> None:
    for row in exposure_table(data):
        print(f"{row['contact']}  {row['source_class']}→{row['target_class']}  "
              f"{row['day']}  {row['kind']}/{row['content']}  "
              f"[{TIMING_LABEL[row['timing']]}]")


def cmd_outcomes(data, args) -> None:
    anchor = _dt.date.fromisoformat(args.anchor)
    outcomes = reconcile(data, anchor)
    for item in outcomes:
        if item.status == "repeat_visitor":
            continue
        print(f"{item.class_id} {item.child:8s} 臂={item.assigned:7s} "
              f"状态={item.status:22s} 得分={_signed(item.score_ratio)} "
              f"答卷={item.answer_id or '—'}")
        if args.verbose:
            print(f"    {item.detail}")
    counts = secondary_answer_counts(data)
    print(f"\n另计：席间练习 {counts['practice']} 份；在家迁移答案 {counts['transfer_home']} 份")


def cmd_results(data, args) -> None:
    anchor = _dt.date.fromisoformat(args.anchor)
    results = pair_results(data, anchor)
    print(f"核对日 {anchor}（收卷期未结束的 pending 不计缺测）\n")
    print(f"{'区组':5s} {'分级':22s} {'成熟':4s} {'对照缺测':8s} {'提示缺测':8s} "
          f"{'缺测差':8s} {'hint-control':12s}")
    for pair, r in results.items():
        print(
            f"{pair:5s} {STATUS_LABEL[r.status]:22s} "
            f"{('是' if r.mature else '否'):4s} "
            f"{_pct(r.control.missing_rate):8s} {_pct(r.hint.missing_rate):8s} "
            f"{_pct(r.missing_gap):8s} {_signed(r.gain):12s}"
        )
    primary = primary_aggregate(data, anchor)
    conditional = conditional_aggregate(data, anchor)
    print("\nITT 可估计区组汇总（采用证据口径）")
    _print_aggregate(primary)
    print("\n有交流条件区组汇总（单独报告，不进采用证据）")
    _print_aggregate(conditional)


def _print_aggregate(agg) -> None:
    print(f"  区组数={agg.pair_count}  平均增益={_signed(agg.mean_gain)}  "
          f"95%CI=[{_signed(agg.ci_low)}, {_signed(agg.ci_high)}]")
    print(f"  最大臂间缺测率差={_pct(agg.missing_gap_max)}  "
          f"2-3年级负担：control={_pct(agg.burden_control)} "
          f"hint={_pct(agg.burden_hint)} 最大={_pct(agg.burden_max)}")
    if agg.excluded_pairs:
        print("  未纳入：")
        for pair, reason in sorted(agg.excluded_pairs.items()):
            print(f"    {pair}: {reason}")


def cmd_review(data, _args) -> None:
    for decision in evaluate_all(data):
        r = decision.review
        print(f"== {r.review}（{r.use}，{r.day}，目标={r.target}） ==")
        print(f"决定：{decision.decision}；成熟区组 {len(decision.mature_pairs)} 个："
              f"{', '.join(decision.mature_pairs)}")
        for name, check in decision.checks.items():
            if name == "gain_floor":
                observed = (
                    f"均值 {_signed(check.get('mean_gain'))} "
                    f"CI[{_signed(check.get('ci_low'))}, {_signed(check.get('ci_high'))}]"
                )
            elif name == "burden":
                observed = (
                    f"最大 {_pct(check.get('observed'))} "
                    f"(control {_pct(check.get('control'))}, hint {_pct(check.get('hint'))})"
                )
            else:
                observed = check.get("observed", "")
            print(f"  [{'通过' if check['pass'] else '未过'}] {name}: "
                  f"观测={observed} 阈值={check['threshold']} — {check['detail']}")
        _print_aggregate(decision.primary)
        if decision.conditional.pair_count:
            print("  有交流条件结果（不进采用证据）：")
            _print_aggregate(decision.conditional)
        for note in decision.notes:
            print(f"  注：{note}")
        print()


def cmd_schedule(data, _args) -> None:
    report = assess_schedule(data)
    print("教师提示接触记录：")
    for teacher, evidence in sorted(report.exposed_teachers.items()):
        print(f"  {teacher}: {'；'.join(evidence)}")
    print("\n候选场评估：")
    for item in report.candidates:
        c = item.candidate
        flag = "可作未暴露对照" if item.eligible_control else "不可作未暴露对照"
        print(f"  {c.candidate} {c.day} {c.school} {c.grade}年级 师{c.teacher} "
              f"block={c.block} 状态={c.state} 回访={c.followup_slot or '无'}  => {flag}")
        for reason in item.ineligible_reasons:
            print(f"      - {reason}")
        if item.pair_link:
            print(f"      配对={item.pair_link} "
                  f"当前可整对保留={item.pair_retainable_now} "
                  f"预留时段后可保留={item.pair_retainable_if_slot_held}")
            for blocker in item.pair_blockers:
                print(f"      × {blocker}")
            for condition in item.slot_conditions:
                print(f"      ~ {condition}")
            if item.first_identifiability_loss:
                print(f"      辨识力首失环节：{item.first_identifiability_loss}")
    print("\n回访时段占用：")
    for slot, users in sorted(report.slot_demand.items()):
        print(f"  {slot}: {', '.join(users)}")
    print(f"\n可整对保留的候选：{', '.join(report.retainable_pairs) or '无'}")
    for note in report.notes:
        print(f"  注：{note}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="studytool",
        description="亲子研学提示试验：可估计性分级、逐人答卷核对、复看与排课",
    )
    parser.add_argument("--data", default="data", help="CSV 资料目录（默认 data）")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("check", help="核验资料格式、键值与关联").set_defaults(func=cmd_check)
    p = sub.add_parser("pairs", help="团群可估计性分级")
    p.add_argument("-v", "--verbose", action="store_true")
    p.set_defaults(func=cmd_pairs)
    sub.add_parser("contacts", help="时序接触逐条时点").set_defaults(func=cmd_contacts)
    p = sub.add_parser("outcomes", help="逐人迁移答卷核对")
    p.add_argument("--anchor", required=True, help="核对日 YYYY-MM-DD")
    p.add_argument("-v", "--verbose", action="store_true")
    p.set_defaults(func=cmd_outcomes)
    p = sub.add_parser("results", help="区组效果、缺测与负担汇总")
    p.add_argument("--anchor", required=True, help="核对日 YYYY-MM-DD")
    p.set_defaults(func=cmd_results)
    sub.add_parser("review", help="按 review_plan 执行复看判定").set_defaults(func=cmd_review)
    sub.add_parser("schedule", help="下一轮候选排课可行性").set_defaults(func=cmd_schedule)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    data = load_trial(Path(args.data))
    args.func(data, args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
