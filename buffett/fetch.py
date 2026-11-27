#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""低频获取乐咕乐股（AKShare）巴菲特指标，校验后输出十年序列。"""
from __future__ import annotations

import argparse
from bisect import bisect_left, bisect_right, insort
from collections import deque
from datetime import date, datetime
import json
import logging
import math
import os
from pathlib import Path
import tempfile
from zoneinfo import ZoneInfo

import pandas as pd
from dateutil.relativedelta import relativedelta

LOG = logging.getLogger("buffett")
REQUIRED = ("日期", "总市值", "GDP")
SOURCE = "AKShare / 乐咕乐股 stock_buffett_index_lg"
MIN_WINDOW = 30


def normalize(raw: pd.DataFrame, *, years: int = 10, today: date | None = None) -> tuple[pd.DataFrame, dict]:
    """要求数值完整；同日期完全相同的源记录只计一次，冲突即报错。"""
    if not 1 <= years <= 20:
        raise ValueError("--years 必须在 1 至 20 年之间")
    if not isinstance(raw, pd.DataFrame) or raw.empty:
        raise ValueError("巴菲特指标接口无数据")
    if set(REQUIRED).difference(raw.columns):
        raise ValueError(f"接口缺少必要列：{sorted(set(REQUIRED) - set(raw.columns))}")
    frame = raw.loc[:, REQUIRED].copy()
    frame.columns = ["date", "tmc", "gdp"]
    frame["date"] = pd.to_datetime(frame["date"], errors="raise").dt.normalize()
    if frame["date"].isna().any():
        raise ValueError("数据包含空日期")
    for field in ("tmc", "gdp"):
        frame[field] = pd.to_numeric(frame[field], errors="raise").astype("float64")
        if (not frame[field].map(math.isfinite).all()) or (frame[field] <= 0).any():
            raise ValueError(f"{field} 包含空值、非有限数或非正值")
    # 接口偶有相同日期的重复行；只允许逐字段完全一致的重复。
    conflicted = frame.groupby("date", sort=False)[["tmc", "gdp"]].nunique(dropna=False).gt(1).any(axis=1)
    if conflicted.any():
        raise ValueError(f"同一日期的总市值或 GDP 存在冲突：{list(conflicted[conflicted].index.date)[:5]}")
    duplicate_count = int(frame.duplicated("date").sum())
    frame = frame.drop_duplicates("date").sort_values("date").reset_index(drop=True)
    if duplicate_count:
        LOG.warning("接口含 %d 条完全相同的日期记录，仅保留每日期一条", duplicate_count)
    today = today or datetime.now(ZoneInfo("Asia/Shanghai")).date()
    if frame["date"].iloc[-1].date() > today:
        raise ValueError("接口出现未来日期")
    frame["buffett"] = frame["tmc"].div(frame["gdp"]).mul(100)
    if not frame["buffett"].map(math.isfinite).all():
        raise ValueError("巴菲特指标计算出现非有限数")

    # 截止每一日，按该日向前十个日历年的有效样本，计算同值平均秩百分位。
    window: deque[tuple[date, float]] = deque()
    sorted_values: list[float] = []
    ranks: list[float | None] = []
    sizes: list[int] = []
    for row in frame.itertuples(index=False):
        day = row.date.date()
        cutoff = day - relativedelta(years=years)
        while window and window[0][0] < cutoff:
            _, old = window.popleft()
            sorted_values.pop(bisect_left(sorted_values, old))
        value = float(row.buffett)
        insort(sorted_values, value)
        window.append((day, value))
        count = len(sorted_values)
        left, right = bisect_left(sorted_values, value), bisect_right(sorted_values, value)
        ranks.append(100 * (left + 1 + right) / (2 * count) if count >= MIN_WINDOW else None)
        sizes.append(count)
    frame["pctile_10y"] = ranks
    frame["window_count"] = sizes
    last_day = frame["date"].iloc[-1].date()
    subset = frame.loc[frame["date"].dt.date >= last_day - relativedelta(years=years)].copy()
    if len(subset) < MIN_WINDOW or pd.isna(subset["pctile_10y"].iloc[-1]):
        raise ValueError("近十年有效记录不足，不能计算百分位")
    ratio = subset["buffett"]
    # 十年有效样本不得由长期滞后数据冒充；休市连续数日仍允许展示其原数据日。
    if (today - last_day).days > 14:
        raise ValueError(f"巴菲特指标最新数据 {last_day} 距当前 {today} 已超过 14 天，本次停止部署")
    stats = {
        "latest_date": last_day.isoformat(),
        "latest": float(ratio.iloc[-1]),
        "latest_pct": float(subset["pctile_10y"].iloc[-1]),
        "latest_tmc": float(subset["tmc"].iloc[-1]),
        "latest_gdp": float(subset["gdp"].iloc[-1]),
        "latest_window_count": int(subset["window_count"].iloc[-1]),
        "mean": float(ratio.mean()),
        "median": float(ratio.median()),
        "p10": float(ratio.quantile(.10)),
        "p90": float(ratio.quantile(.90)),
        "sample_count": len(subset),
        "start_date": subset["date"].iloc[0].date().isoformat(),
    }
    if not (0 <= stats["latest_pct"] <= 100):
        raise ValueError("近十年百分位不在 0—100 范围内")
    return subset, stats


def prepare_payload(subset: pd.DataFrame, stats: dict) -> dict:
    rows = []
    for r in subset.itertuples(index=False):
        rows.append({"date": r.date.date().isoformat(), "tmc": float(r.tmc),
                     "gdp": float(r.gdp), "buffett": float(r.buffett),
                     "pctile_10y": None if pd.isna(r.pctile_10y) else float(r.pctile_10y)})
    return {"source": SOURCE, "basis": "A股总市值/接口给出的上年度名义GDP×100；十年滚动平均秩百分位",
            "years": 10, "stats": stats, "rows": rows}


def atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix="buffett-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:
            stream.write(text)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def fetch_and_save(output: Path, csv_path: Path, years: int = 10, fetcher=None, today: date | None = None):
    if fetcher is None:
        import akshare as ak
        fetcher = ak.stock_buffett_index_lg
    LOG.info("开始一次性获取全历史数据（不分页、不并发）：%s", SOURCE)
    raw = fetcher()  # 接口限制或网络异常直接失败，不更换代理、身份或请求通道。
    subset, stats = normalize(raw, years=years, today=today)
    payload = prepare_payload(subset, stats)
    payload["years"] = years
    csv_frame = pd.DataFrame(payload["rows"])
    atomic_text(csv_path, csv_frame.to_csv(index=False))
    atomic_text(output, json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":")).replace("<", "\\u003c"))
    LOG.info("有效日期 %s — %s；样本 %d 条；指标 %.2f%%；近 %d 年百分位 %.2f%%",
             stats["start_date"], stats["latest_date"], stats["sample_count"], stats["latest"], years, stats["latest_pct"])
    LOG.info("保存 %s 和 %s", output, csv_path)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="更新 A 股巴菲特指标，生成数据 JSON 和 CSV")
    parser.add_argument("--years", type=int, default=10)
    parser.add_argument("--output", type=Path, default=Path("data/buffett.json"))
    parser.add_argument("--csv", type=Path, default=Path("data/buffett_indicator_data.csv"))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", handlers=[logging.StreamHandler(), logging.FileHandler("run.log", encoding="utf-8")])
    try:
        fetch_and_save(args.output, args.csv, args.years)
        return 0
    except Exception:
        LOG.exception("巴菲特指标更新失败；禁止用空值或旧数据冒充新数据")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
