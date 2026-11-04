#!/usr/bin/env python3
"""将原脚本导出的 Excel 转换为 GitHub Pages 单页图表。"""
import argparse
import json
import logging
from datetime import datetime
from pathlib import Path

import pandas as pd

LOG = logging.getLogger(__name__)
COLUMNS = [
    "交易日期", "收盘-沪深300", "融资余额(亿元)", "融资融券余额(亿元)",
    "融资买入额(亿元)", "当日融资买入额占融资余额比例",
    "当日融资买入额占融资余额比例近五年百分位",
    "当日参与交易投资者占有负债投资者比例近五年百分位",
    "平均维持担保比例(%)", "当日平均维持担保比例近五年百分位",
]


def build(input_path: Path, output_path: Path) -> None:
    frame = pd.read_excel(input_path, sheet_name="合并分析")
    missing = set(COLUMNS) - set(frame.columns)
    if missing:
        raise ValueError(f"Excel 缺少字段：{sorted(missing)}")
    frame["交易日期"] = pd.to_datetime(frame["交易日期"], errors="raise")
    if frame.empty or frame["交易日期"].duplicated().any():
        raise ValueError("数据为空或交易日期重复")
    frame = frame.sort_values("交易日期")
    data = []
    for record in frame[COLUMNS].to_dict("records"):
        row = {}
        for key, value in record.items():
            if key == "交易日期":
                row[key] = value.strftime("%Y-%m-%d")
            else:
                row[key] = None if pd.isna(value) else float(value)
        data.append(row)
    template = Path(__file__).resolve().parent / "site_template.html"
    html = template.read_text(encoding="utf-8")
    payload = json.dumps(data, ensure_ascii=False, allow_nan=False, separators=(",", ":")).replace("<", "\\u003c")
    html = html.replace("/*__DATA__*/[]", payload)
    html = html.replace("__GENERATED_AT__", datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z"))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    LOG.info("生成 %s；记录 %d 条；最新交易日 %s", output_path, len(data), data[-1]["交易日期"])


def main() -> int:
    parser = argparse.ArgumentParser(description="从融资融券 Excel 生成图表页面")
    parser.add_argument("--input", type=Path, default=Path("data/融资融券近五年合并分析.xlsx"))
    parser.add_argument("--output", type=Path, default=Path("docs/index.html"))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", handlers=[logging.StreamHandler(), logging.FileHandler("run.log", encoding="utf-8")])
    try:
        build(args.input, args.output)
        return 0
    except Exception:
        LOG.exception("页面生成失败")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
