# 亲子研学提示方式的延后学习试验

博物馆组织的线索提示试课，留有成对分派、跨团接触和一周后独立迁移的记录。 `data/` 中的记录均为虚构业务数据。

使用 Python 3.11.2。资料核验与分析仅依赖标准库。

在仓库根目录核验资料格式、键值与关联记录：

```bash
python3 -m unittest discover -s tests -v
```

各表来源及字段约定见 [资料约定](data-contract.md)，工具的判定口径与需求对应关系见
[分析口径与判定规则](METHODOLOGY.md)。

## 连续更新工具 `studytool/`

随新排课和新答卷落盘后重跑同一命令即可更新结论，所有输出均为只读分析：

```bash
python3 -m studytool.cli --data data check                       # 六张表语义核验
python3 -m studytool.cli --data data pairs -v                    # 团群可估计性三级分级
python3 -m studytool.cli --data data contacts                    # 时序接触逐条时点
python3 -m studytool.cli --data data outcomes --anchor 2026-11-23 -v  # 逐人答卷核对
python3 -m studytool.cli --data data results --anchor 2026-11-26      # 效果/缺测/负担
python3 -m studytool.cli --data data review                      # 复看决定点判定
python3 -m studytool.cli --data data schedule                    # 下一轮排课可行性
```

工具回答三类问题：

1. **哪些团群的随机比较还能估计指派效果**：`itt_estimable` /
   `exposure_conditional`（仅有交流条件结果）/ `unidentifiable`（无法区分）。
2. **证据是否足以采用新提示**：只使用成熟且 ITT 可估计的区组，按
   `review_plan` 的增益下界、缺测差、负担和最少区组数判定；探索复看只登记不采用，
   单场回卷早不单独决定采用。
3. **下一轮候选安排哪些可做**：未暴露对照资格、回访时段冲突、必须整对保留的
   候选对，以及换班或通知家长后最先失去辨别条件的环节。
