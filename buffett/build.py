#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""将通过校验的巴菲特指标嵌入单文件 GitHub Pages 看板。"""
import argparse
from bisect import bisect_left, bisect_right
import json
import logging
import math
import os
from datetime import date
from pathlib import Path
import tempfile
from statistics import fmean, median

from dateutil.relativedelta import relativedelta

LOG = logging.getLogger("buffett-build")
MARKER = "/*__BUFFETT_DATA__*/{}"


def check_payload(payload: dict) -> None:
    if not isinstance(payload, dict) or not isinstance(payload.get("rows"), list):
        raise ValueError("巴菲特指标 JSON 格式不正确")
    rows = payload["rows"]
    stats = payload.get("stats")
    if len(rows) < 30 or not isinstance(stats, dict):
        raise ValueError("巴菲特指标样本不足或缺少统计结果")
    dates = [date.fromisoformat(r["date"]) for r in rows]
    if dates != sorted(set(dates)):
        raise ValueError("交易日期不是严格递增且唯一")
    values = []
    for r in rows:
        tmc, gdp, ratio = (float(r[k]) for k in ("tmc", "gdp", "buffett"))
        if any(not math.isfinite(v) for v in (tmc, gdp, ratio)) or min(tmc, gdp) <= 0:
            raise ValueError("市值/GDP/指标含无效值")
        if not math.isclose(ratio, tmc / gdp * 100, rel_tol=1e-10):
            raise ValueError(f"指标与市值/GDP 不一致：{r['date']}")
        p = r.get("pctile_10y")
        if p is not None and (not math.isfinite(float(p)) or not 0 <= float(p) <= 100):
            raise ValueError("近十年百分位越界")
        values.append(ratio)
    if stats.get("latest_date") != rows[-1]["date"] or not math.isclose(float(stats["latest"]), values[-1], rel_tol=1e-10):
        raise ValueError("最新日期/指标与明细不一致")
    if stats.get("sample_count") != len(rows) or stats.get("start_date") != rows[0]["date"]:
        raise ValueError("样本数或起始日期与明细不一致")
    if not math.isclose(float(stats["latest_pct"]), float(rows[-1]["pctile_10y"]), rel_tol=1e-10):
        raise ValueError("最新百分位与明细不一致")
    for k in ("latest_tmc", "latest_gdp", "mean", "median", "p10", "p90"):
        if not math.isfinite(float(stats[k])):
            raise ValueError(f"统计项 {k} 非有限数")
    if not math.isclose(float(stats["latest_tmc"]), float(rows[-1]["tmc"]), rel_tol=1e-10):
        raise ValueError("最新总市值不一致")
    if not math.isclose(float(stats["latest_gdp"]), float(rows[-1]["gdp"]), rel_tol=1e-10):
        raise ValueError("最新 GDP 不一致")
    # 输出端独立复核所有显示的衍生统计值，避免页面文案和图表脱节。
    ordered = sorted(values)
    def linear_quantile(p):
        pos = (len(ordered) - 1) * p
        left = math.floor(pos)
        right = math.ceil(pos)
        return ordered[left] + (ordered[right] - ordered[left]) * (pos - left)
    expected = {"mean": fmean(values), "median": median(values),
                "p10": linear_quantile(.10), "p90": linear_quantile(.90)}
    for key, value in expected.items():
        if not math.isclose(float(stats[key]), value, rel_tol=1e-10):
            raise ValueError(f"{key} 与明细不一致")
    # 最新百分位在最新交易日前十年的序列上计算，同值取平均秩。
    cutoff = dates[-1] - relativedelta(years=int(payload.get("years", 10)))
    window = sorted(v for d, v in zip(dates, values) if d >= cutoff)
    count = len(window)
    left, right = bisect_left(window, values[-1]), bisect_right(window, values[-1])
    latest_pct = 100 * (left + 1 + right) / (2 * count)
    if stats.get("latest_window_count") != count or not math.isclose(float(stats["latest_pct"]), latest_pct, rel_tol=1e-10):
        raise ValueError("最新十年百分位或有效样本数与明细不一致")


def build(source: Path, target: Path, template: Path | None = None) -> None:
    payload = json.loads(source.read_text(encoding="utf-8"))
    check_payload(payload)
    template = template or Path(__file__).resolve().parent / "template.html"
    html = template.read_text(encoding="utf-8")
    if html.count(MARKER) != 1:
        raise ValueError("看板模板缺少唯一的数据注入占位符")
    inline = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":")).replace("<", "\\u003c")
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix="buffett-page-", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(html.replace(MARKER, inline))
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    LOG.info("已生成 %s；%d 条记录；最新 %s", target, len(payload["rows"]), payload["stats"]["latest_date"])


def main() -> int:
    parser = argparse.ArgumentParser(description="生成巴菲特指标网页")
    parser.add_argument("--input", type=Path, default=Path("data/buffett.json"))
    parser.add_argument("--output", type=Path, default=Path("docs/buffett.html"))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", handlers=[logging.StreamHandler(), logging.FileHandler("run.log", encoding="utf-8")])
    try:
        build(args.input, args.output)
        return 0
    except Exception:
        LOG.exception("巴菲特指标页面生成失败")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
