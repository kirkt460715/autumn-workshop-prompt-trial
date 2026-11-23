# 分析口径与判定规则

本文件把 `studytool/` 的每个判定与需求和 [资料约定](data-contract.md) 逐条对应。
工具只读 CSV、只用 Python 标准库；新排课或新答卷落盘后重跑同一命令即可连续更新。

## 1. 入组与分母

- 随机单位是成对研学团（`classes.pair` 为随机区组），每对开课前登记一个
  `control` 与一个 `hint`。
- 重复到访的孩子按**首次符合资格的团**保留分派；名册中的 `H-repeat` 行
  （K020、K091、K110）不进入到访团分母，其作答仅作暴露与过程留档。
- ITT 分母 = 到课孩子（`attendance` 为 `present` 或 `left`），剔除重复到访；
  未到课（`absent`）不入组。退出者（`left`）保留在原分派臂，缺结果不补分母。

## 2. 主结果与逐人答卷核对

主结果只认**开课后第 7–10 个自然日、陌生展品前、馆内独立完成的迁移作答**
（`source=transfer`、`setting=gallery`、`independent=yes`）。允许当次有效零分。

| 状态 | 含义 | 是否进主结果 |
| --- | --- | --- |
| `valid_gallery` | 窗口内馆内独立卷（含零分） | 是 |
| `valid_home` | 窗口内独立但在家完成 | 否，另一回收途径另计 |
| `process_noncompliant` | 窗口内但过程不合规（如 `independent=unknown`） | 否，计缺测 |
| `out_of_window` | 窗口外（第 6 日提前卷、第 11 日后迟到卷） | 否，计缺测 |
| `window_open_no_paper` | 核对日早于第 10 日、暂无合条件卷 | 不判定，pending |
| `no_paper_at_close` | 第 10 日收卷期满仍无卷 | 否，计缺测 |
| `exited` | 开课时到课随后退出 | 留分母，单列保护指标 |
| `repeat_visitor` | 重复到访 | 不进该团分母 |
| `absent` | 未到课 | 不入组 |

- 收卷期未结束时一律是 pending，**不能因为某场回卷早就单独决定采用**。
- 连续更新快照：核对日之后日期的答卷当时尚未回收，不参与判定；窗口未走满时
  已有的提前卷/不合规卷也保持 pending（仍可能被后续合条件卷替代），收卷期满
  重跑同一命令才翻成有效或缺测。
- 课堂练习（`practice/room`）与在家答案（`home`）分别计数，不进主结果。
- 报名名册核对：无名册对应的答卷、重复记录键、计分越界在加载阶段直接报错。

## 3. 时序交流与团群可估计性

交流边按 `contacts.day` 的证据日与目标团授课日比较：

- `timely`：第 0–10 日内的**传递性**接触（教师提示示范、家长拿到完整迁移题、
  跨团重复到访）；
- `non_transmitting`：内容为“仅场馆介绍”，不含提示做法，不构成方法暴露；
- `late`：第 10 日收卷期之后，不影响本轮主结果。

并查集把 `timely` 传递边两端的团连成交流团群。区组三级分类：

1. `itt_estimable`：两臂实际授课与指派一致，且无 `timely` 传递边连入。
   区内随机比较仍估计**指派效果（ITT）**。
2. `exposure_conditional`：两臂仍形成对照，但有换班或交流边，只支持
   **有交流条件下的结果**，单独报告、不进采用证据。
3. `unidentifiable`：对照臂实际收到提示（如 K030、K080 实际授 hint，
   与 hint 臂同为 hint），两臂不再有方法对照，**根本无法区分两种提示**。

当前数据：18 个 ITT 区组、4 个有交流条件区组（P07、P09、P11、P15）、
2 个无法区分区组（P03、P08）。

## 4. 效果、缺测与负担

- 区组增益 = 区内 hint 臂与 control 臂主结果均值之差（满分比例分）。
- 汇总只对**成熟**（核对日 ≥ 授课日 +10 天）且符合分级口径的区组，
  报告配对平均增益与双侧 95% t 置信区间（标准库实现，分位数表在
  `analysis._T_CRIT_95`）。
- 缺测率差 = 区内两臂缺测人数/分母之差的绝对值；pending 不计缺测。
- 保护指标：开课时 2–3 年级孩子中，限时未完成（`overtime=yes`）或退出
  （`left`）的比例，按原分派臂分别报告。

## 5. 复看决定点（`review_plan`）

- 探索复看（V1）只登记所用结果与时点、成熟区组和点估计，**永不产生采用决定**。
- 正式复看（V2、V3）必须同时通过四项：
  1. 成熟且 ITT 可估计、符合 `target` 的区组数 ≥ `min_pairs`；
  2. 增益 95% 置信区间下界 ≥ `gain_floor`；
  3. 最大臂间缺测率差 ≤ `missing_gap_ceiling`；
  4. 2–3 年级最大负担率 ≤ `burden_ceiling`。
- 受交流团群的条件结果随复看一并可查，但不参与采用判定。
- 当前数据下 V2、V3 均为 `hold`：区组数达标，但增益下界、缺测差或负担未过线。

## 6. 下一轮排课

未暴露对照资格（三者同时满足）：

1. `prior_material=no`（家长未拿到题）；
2. 带班教师无**异常提示接触**——即没有在换班中实际授过与指派不符的 hint，
   也没有涉入教师类提示示范边。正常按指派带 hint 团属于试验内合法分工，
   不算异常接触，否则同一批老师永远无法承担对照；
3. 已订一周后独立回访时段（`followup_slot` 非空）。

硬约束与输出：

- 同一 `block` 一名教师只能带一场；同一 `followup_slot` 只够一个团回访。
- 候选对必须**整对保留**；工具区分“硬阻断”（资格丧失）与“预留时段即可解除”
  （时段冲突），并给出辨识力首失环节：
  - 换班/教师接触 → 先失去提示方式区分条件；
  - 通知家长（`prior_material=yes`）→ 题目区分条件丧失；
  - 时段被占且不预留 → 对照失去一周后回访，不能在确认采用的同时算作可做。
- 当前数据只有 NC6（教师 L6 无异常接触、家长未拿题）具备对照资格，
  NC6~NC7 在为 NC6 保留 FOL4（移出 NC5 占用）的前提下可整对保留；
  NC1~NC2、NC4~NC5 为硬阻断，NC3 无配对不能构成比较。

## 7. 命令

```bash
python3 -m unittest discover -s tests -v          # 全量核验
python3 -m studytool.cli --data data check        # 资料格式/键值/关联核验
python3 -m studytool.cli --data data pairs -v     # 团群三级分级与理由
python3 -m studytool.cli --data data contacts     # 逐条接触时点
python3 -m studytool.cli --data data outcomes --anchor 2026-11-23 -v
python3 -m studytool.cli --data data results --anchor 2026-11-26
python3 -m studytool.cli --data data review       # 按 review_plan 出复看判定
python3 -m studytool.cli --data data schedule     # 下一轮排课可行性
```

在启用 `-I` 的环境中，用 `PYTHONPATH` 不生效，可改用：

```bash
python3 -I -c "import sys; sys.path.insert(0,'.'); \
  from studytool.cli import main; raise SystemExit(main(['--data','data','review']))"
```
