# 资料约定

CSV 采用 UTF-8 编码。日期使用年、月、日，数值以十进制表示。字段为空表示来源未提供该项或该项不适用，含义以表约定为准。

每对团开课前分派一个 control 和一个 hint，pair 是随机区组。school、教师和家庭的接触含义见 contacts 和实际带班。主结果是第 7 到第 10 个自然日在陌生展品前独立答题，允许当次有效零分；到第 10 日结束才视为已走满。课当天的课堂练习和 home 是另外的回收途径。出勤后没有合条件结果的孩子仍在原分组分母，保护指标使用开课时 2 至 3 年级的限时未完成或退出。
下一轮统一以相同 followup_slot 表示只够一个团独立回访的展品时段，教师在同一 block 只能带一场。有 prior_material 或实际老师已接触提示的团不能作为未暴露对照。followup_slot 中空值表示没有已订回访时段。正式复看和保护线由 review_plan 登记。

## 文件来源

- `classes.csv`。课次原始随机分派和课内实际带班。 记录键为 `class_id`。
- `children.csv`。合格报名、分派课签到和限时负担登记。 记录键为 `class_id`、`child`。
- `answers.csv`。一周后的迁移作答以及不同过程的练习、回家作答留档。 记录键为 `answer_id`。
- `contacts.csv`。跨团交流或接触提示记录；有证据的时间以 day 为准。 记录键为 `contact`。
- `review_plan.csv`。已经登记的复看决定点，比例字段在零到一之间，gain_floor 以满分比例差计。 记录键为 `review`。
- `next_classes.csv`。待排、已留对照以及值班变动记录。 记录键为 `candidate`。
