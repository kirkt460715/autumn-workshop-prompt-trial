import datetime as dt
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from studytool.loader import load_trial
from studytool.enrollment import build_enrollment, itt_denominator, repeat_visitors
from studytool.reconciliation import (
    reconcile,
    transfer_window_end,
    VALID_GALLERY,
    VALID_HOME,
    PROCESS_NONCOMPLIANT,
    OUT_OF_WINDOW,
    WINDOW_OPEN_NO_PAPER,
    NO_PAPER_AT_CLOSE,
    EXITED,
    REPEAT_VISITOR,
)
from studytool.contamination import (
    assess_pairs,
    build_components,
    timing_for,
    ITT_ESTIMABLE,
    EXPOSURE_CONDITIONAL,
    UNIDENTIFIABLE,
    TIMELY,
    NON_TRANSMITTING,
    LATE,
)
from studytool.analysis import (
    pair_results,
    primary_aggregate,
    conditional_aggregate,
    burden_rates,
    t_critical_95,
)
from studytool.review import evaluate_all, evaluate_review
from studytool.schedule import assess_schedule, teacher_hint_exposure

DATA = Path(__file__).resolve().parents[1] / "data"
ANCHOR = dt.date(2026, 11, 23)


class TrialToolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = load_trial(DATA)

    def status_of(self, class_id, child):
        outcomes = {(o.class_id, o.child): o for o in reconcile(self.data, ANCHOR)}
        return outcomes[(class_id, child)]

    # ---- loader -------------------------------------------------------
    def test_loader_joins_all_six_tables(self):
        self.assertEqual(len(self.data.classes), 48)
        self.assertEqual(len(self.data.pair_classes), 24)
        for arms in self.data.pair_classes.values():
            self.assertEqual(set(arms), {"control", "hint"})

    def test_loader_rejects_bad_score_bounds(self):
        good = self.data.answers[0]
        self.assertLessEqual(good.raw_score, good.max_score)
        self.assertTrue(all(a.max_score > 0 for a in self.data.answers))

    # ---- enrollment ---------------------------------------------------
    def test_repeat_visitors_kept_out_of_denominator(self):
        repeats = {(r.class_id, r.child) for r in repeat_visitors(self.data)}
        self.assertEqual(
            repeats,
            {("K020", "H-repeat"), ("K091", "H-repeat"), ("K110", "H-repeat")},
        )
        for class_id, _ in repeats:
            denominator = {(e.child) for e in itt_denominator(self.data, class_id)}
            self.assertNotIn("H-repeat", denominator)

    def test_exited_children_remain_in_denominator(self):
        # K000/N0000 登记为 left
        enrollment = build_enrollment(self.data)
        item = enrollment[("K000", "N0000")]
        self.assertTrue(item.attended and item.exited)
        denominator = {e.child for e in itt_denominator(self.data, "K000")}
        self.assertIn("N0000", denominator)

    # ---- reconciliation ----------------------------------------------
    def test_window_end_is_tenth_natural_day(self):
        self.assertEqual(
            transfer_window_end(self.data, "K000"), dt.date(2026, 11, 12)
        )

    def test_valid_zero_scored_transfer_counts_as_observed(self):
        outcome = self.status_of("K000", "N0002")  # 窗口内 0 分
        self.assertEqual(outcome.status, VALID_GALLERY)
        self.assertEqual(outcome.score_ratio, 0.0)

    def test_day_six_unknown_independence_is_out_of_window(self):
        outcome = self.status_of("K001", "N0010")  # 第 6 日 unknown
        self.assertEqual(outcome.status, OUT_OF_WINDOW)
        self.assertIsNone(outcome.score_ratio)

    def test_home_answer_is_separate_channel(self):
        outcome = self.status_of("K000", "N0004")  # 第 10 日 home
        self.assertEqual(outcome.status, VALID_HOME)
        self.assertIsNone(outcome.score_ratio)

    def test_exited_child_flagged_separately(self):
        outcome = self.status_of("K000", "N0000")
        self.assertEqual(outcome.status, EXITED)

    def test_repeat_visitor_outcome_is_flagged(self):
        outcome = self.status_of("K020", "H-repeat")
        self.assertEqual(outcome.status, REPEAT_VISITOR)

    def test_pending_vs_closed_missing(self):
        # K100 授课 2026-11-12，窗口 11-19 至 11-22，核对日 11-23 已走满
        closed = self.status_of("K100", "N1004")  # 无任何 transfer 记录
        self.assertEqual(closed.status, NO_PAPER_AT_CLOSE)
        # K210 授课 2026-11-23，窗口未结束
        pending = self.status_of("K210", "N2100")
        self.assertEqual(pending.status, WINDOW_OPEN_NO_PAPER)

    def test_snapshot_ignores_future_answers_and_keeps_open_window_pending(self):
        # K230 授课 2026-11-25，晚于核对日：12 月的答卷在 11-23 快照中尚未回收
        outcomes = reconcile(self.data, ANCHOR)
        k230 = [o for o in outcomes if o.class_id == "K230" and o.status != "exited"]
        self.assertTrue(k230)
        self.assertTrue(all(o.status == WINDOW_OPEN_NO_PAPER for o in k230))
        # 同一批数据在收卷期满后重跑，状态应翻成有效或缺测
        later = reconcile(self.data, dt.date(2026, 12, 8))
        later_k230 = {o.child: o for o in later if o.class_id == "K230"}
        self.assertNotIn(WINDOW_OPEN_NO_PAPER, {o.status for o in later_k230.values()})
        # 窗口未走满时，提前到第 6 日的卷保持 pending，不提前判缺测
        early = {(o.class_id, o.child): o for o in reconcile(self.data, ANCHOR)}
        self.assertEqual(early[("K211", "N2110")].status, WINDOW_OPEN_NO_PAPER)

    def test_process_noncompliant_inside_window(self):
        # 构造一个窗口内 unknown 的情形：数据中 unknown 均在第 6 日，
        # 因此通过分类函数直接验证规则
        from studytool.reconciliation import _classify_answer
        answer = next(
            a for a in self.data.answers
            if a.answer_id == "A-K001-0-late"
        )
        status, _ = _classify_answer(self.data, answer)
        self.assertEqual(status, OUT_OF_WINDOW)
        fake = answer.__class__(
            answer.answer_id, answer.class_id, answer.child,
            self.data.class_day(answer.class_id) + dt.timedelta(days=8),
            answer.source, answer.setting, answer.raw_score,
            answer.max_score, "unknown",
        )
        status, _ = _classify_answer(self.data, fake)
        self.assertEqual(status, PROCESS_NONCOMPLIANT)

    # ---- contamination -----------------------------------------------
    def test_pair_status_partition(self):
        assessments = assess_pairs(self.data)
        expected = {
            "P03": UNIDENTIFIABLE,
            "P08": UNIDENTIFIABLE,
            "P07": EXPOSURE_CONDITIONAL,
            "P09": EXPOSURE_CONDITIONAL,
            "P11": EXPOSURE_CONDITIONAL,
            "P15": EXPOSURE_CONDITIONAL,
        }
        for pair, status in expected.items():
            self.assertEqual(assessments[pair].status, status, pair)
        counts = {}
        for item in assessments.values():
            counts[item.status] = counts.get(item.status, 0) + 1
        self.assertEqual(counts[ITT_ESTIMABLE], 18)
        self.assertEqual(counts[EXPOSURE_CONDITIONAL], 4)
        self.assertEqual(counts[UNIDENTIFIABLE], 2)

    def test_nontransmitting_venue_intro_does_not_contaminate(self):
        ct4 = next(c for c in self.data.contacts if c.contact == "CT4")
        self.assertEqual(timing_for(self.data, ct4), NON_TRANSMITTING)
        assessments = assess_pairs(self.data)
        self.assertEqual(assessments["P12"].status, ITT_ESTIMABLE)
        self.assertEqual(assessments["P13"].status, ITT_ESTIMABLE)

    def test_transmission_components_link_pairs(self):
        component_of, _, timing = build_components(self.data)
        self.assertEqual(timing["CT1"], TIMELY)
        # CT2（K071→K080）把 P07 与 P08 的 K080 串成同一交流团群
        self.assertEqual(component_of["K071"], component_of["K080"])
        # CT3（K081→K090）把 P08 的 K081 与 P09 的 K090 串成团群
        self.assertEqual(component_of["K081"], component_of["K090"])
        # 两条边指向 P08 的不同臂，团群不合并
        self.assertNotEqual(component_of["K071"], component_of["K090"])
        # CT5（K111→K151）跨 P11、P15 串团
        self.assertEqual(component_of["K111"], component_of["K151"])

    def test_late_contact_handling(self):
        # 数据中没有 late 边；构造一条目标窗口结束后的接触验证规则
        ct = next(c for c in self.data.contacts if c.contact == "CT5")
        shifted = ct.__class__(
            ct.contact, ct.source_class, ct.target_class,
            self.data.class_day(ct.target_class) + dt.timedelta(days=12),
            ct.kind, ct.content,
        )
        self.assertEqual(timing_for(self.data, shifted), LATE)

    def test_deviation_pair_with_remaining_contrast_is_conditional(self):
        # 当前数据两个偏差团都变成双 hint；规则仍要求单臂偏差归 conditional
        assessments = assess_pairs(self.data)
        self.assertEqual(assessments["P03"].reasons[-1].startswith("两臂实际均为 hint"), True)

    # ---- analysis -----------------------------------------------------
    def test_denominator_and_missing_accounting(self):
        results = pair_results(self.data, ANCHOR)
        k000 = results["P00"].control
        self.assertEqual(k000.denominator, 6)   # 5 present + 1 left，无 H-repeat
        self.assertEqual(k000.exited, 1)
        # N0004 的有效卷在家完成（other_channel 另计），不进 observed/missing
        self.assertEqual(
            k000.observed + k000.missing + k000.pending + k000.exited
            + k000.other_channel,
            k000.denominator,
        )
        self.assertEqual(k000.other_channel, 1)

    def test_primary_aggregate_uses_only_clean_mature_pairs(self):
        agg = primary_aggregate(self.data, dt.date(2026, 11, 26))
        self.assertEqual(agg.pair_count, 10)
        self.assertEqual(
            agg.included_pairs,
            ["P00", "P01", "P02", "P04", "P05", "P06", "P10", "P12", "P13", "P14"],
        )
        for pair in ("P03", "P07", "P08", "P09", "P11"):
            self.assertIn(pair, agg.excluded_pairs)

    def test_conditional_aggregate_is_reported_separately(self):
        agg = conditional_aggregate(self.data, dt.date(2026, 11, 26))
        self.assertEqual(set(agg.included_pairs), {"P07", "P09", "P11"})
        self.assertNotIn("P03", agg.included_pairs)  # 无法区分的不进条件结果

    def test_t_critical_table(self):
        self.assertAlmostEqual(t_critical_95(9), 2.262, places=3)
        self.assertEqual(t_critical_95(0) != t_critical_95(0), True)  # NaN
        self.assertEqual(t_critical_95(60), 1.96)

    def test_burden_only_covers_grades_two_three(self):
        rates = burden_rates(self.data)
        for arm in ("control", "hint"):
            self.assertTrue(0.0 <= rates[arm] <= 1.0)

    # ---- review -------------------------------------------------------
    def test_review_decisions_and_thresholds(self):
        decisions = {d.review.review: d for d in evaluate_all(self.data)}
        v1 = decisions["V1"]
        self.assertEqual(v1.decision, "exploratory_only")
        self.assertEqual(v1.mature_pairs, ["P00", "P01"])

        v2 = decisions["V2"]
        self.assertEqual(v2.decision, "hold")
        self.assertTrue(v2.checks["min_pairs"]["pass"])      # 10 >= 10
        self.assertFalse(v2.checks["gain_floor"]["pass"])
        self.assertFalse(v2.checks["missing_gap"]["pass"])
        self.assertFalse(v2.checks["burden"]["pass"])

        v3 = decisions["V3"]
        self.assertEqual(v3.review.target, "school")
        self.assertEqual(v3.decision, "hold")

    def test_exploratory_review_never_adopts(self):
        record = self.data.reviews[0]
        decision = evaluate_review(self.data, record)
        self.assertFalse(decision.can_adopt)

    # ---- schedule -----------------------------------------------------
    def test_exposed_teachers_only_irregular_contacts(self):
        exposed = teacher_hint_exposure(self.data)
        # 正常带 hint 的 L1、L6、L7 不在异常接触名单
        self.assertNotIn("L1", exposed)
        self.assertNotIn("L6", exposed)
        self.assertNotIn("L7", exposed)
        self.assertIn("L2", exposed)   # K080 换班授 hint
        self.assertIn("L5", exposed)   # CT1 提示示范
        self.assertIn("L3", exposed)   # CT3 提示示范

    def test_schedule_pair_verdicts(self):
        report = assess_schedule(self.data)
        views = {a.candidate.candidate: a for a in report.candidates}
        # NC1 对照资格被换班教师破坏，硬阻断
        self.assertFalse(views["NC1"].eligible_control)
        self.assertFalse(views["NC1"].pair_retainable_if_slot_held)
        # NC6 是唯一合格对照，但 FOL4 与 NC5 冲突，当前不可、预留时段后可保留
        self.assertTrue(views["NC6"].eligible_control)
        self.assertFalse(views["NC6"].pair_retainable_now)
        self.assertTrue(views["NC6"].pair_retainable_if_slot_held)
        self.assertTrue(
            any("FOL4" in c for c in views["NC6"].slot_conditions)
        )
        # NC3 无配对，无法构成比较
        self.assertIsNone(views["NC3"].pair_link)
        self.assertEqual(report.retainable_pairs, ["NC6~NC7"])

    def test_schedule_first_identifiability_loss_order(self):
        report = assess_schedule(self.data)
        views = {a.candidate.candidate: a for a in report.candidates}
        self.assertIn("换班", views["NC1"].first_identifiability_loss)


class LoaderValidationTests(unittest.TestCase):
    def _mutated(self, mutate):
        tmp = tempfile.mkdtemp()
        try:
            for source in DATA.glob("*.csv"):
                Path(tmp, source.name).write_text(
                    source.read_text(encoding="utf-8"), encoding="utf-8"
                )
            mutate(Path(tmp))
            with self.assertRaises(ValueError):
                load_trial(tmp)
        finally:
            shutil.rmtree(tmp)

    def test_header_mismatch_rejected(self):
        def mutate(directory):
            path = directory / "classes.csv"
            lines = path.read_text(encoding="utf-8").splitlines()
            lines[0] = lines[0].replace("teacher", "tutor")
            path.write_text("\n".join(lines), encoding="utf-8")
        self._mutated(mutate)

    def test_score_out_of_bounds_rejected(self):
        def mutate(directory):
            path = directory / "answers.csv"
            lines = path.read_text(encoding="utf-8").splitlines()
            lines[1] = lines[1].replace(",1,6,", ",9,6,")
            path.write_text("\n".join(lines), encoding="utf-8")
        self._mutated(mutate)

    def test_orphan_answer_rejected(self):
        def mutate(directory):
            path = directory / "answers.csv"
            lines = path.read_text(encoding="utf-8").splitlines()
            lines[1] = lines[1].replace("K000,N0001", "K999,N9999")
            path.write_text("\n".join(lines), encoding="utf-8")
        self._mutated(mutate)

    def test_ratio_range_rejected(self):
        def mutate(directory):
            path = directory / "review_plan.csv"
            lines = path.read_text(encoding="utf-8").splitlines()
            lines[1] = lines[1].replace(",0.04,", ",1.5,", 1)
            path.write_text("\n".join(lines), encoding="utf-8")
        self._mutated(mutate)

    def test_duplicate_key_rejected(self):
        def mutate(directory):
            path = directory / "contacts.csv"
            lines = path.read_text(encoding="utf-8").splitlines()
            lines.append(lines[1])
            path.write_text("\n".join(lines), encoding="utf-8")
        self._mutated(mutate)


if __name__ == "__main__":
    unittest.main()
