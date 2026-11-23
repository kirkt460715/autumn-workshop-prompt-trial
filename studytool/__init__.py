"""研学提示试验的连续更新工具（仅依赖 Python 标准库）。

模块划分：
- loader：读取并语义核验六张 CSV
- enrollment：报名名册、重复到访与 ITT 分母
- reconciliation：一周后迁移作答的逐人状态判定
- contamination：时序交流与团群可估计性分级
- analysis：配对区组效果、缺测与负担
- review：复看决定点判定
- schedule：下一轮排课的对照可行性与冲突检测
- cli：命令行入口
"""

__all__ = [
    "loader",
    "enrollment",
    "reconciliation",
    "contamination",
    "analysis",
    "review",
    "schedule",
]
