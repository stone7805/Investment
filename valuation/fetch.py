#!/usr/bin/env python3
"""按白名单从中证指数公开数据获取滚动 PE；全部成功后一次性更新缓存。"""
import argparse
import json
import logging
import os
import re
import tempfile
import time
import urllib.error
from datetime import date
from pathlib import Path

import pandas as pd

LOG = logging.getLogger("valuation")
REQUIRED = ["日期", "指数代码", "指数中文简称", "滚动市盈率"]


def load_config(path: Path):
    items = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(items, list) or not items:
        raise ValueError("指数清单不能为空")
    seen = set()
    for item in items:
        if not isinstance(item, dict) or set(item) != {"code", "name", "category"}:
            raise ValueError("清单每项须包含 code/name/category")
        code = item["code"]
        if not isinstance(code, str) or not re.fullmatch(r"\d{6}", code) or code in seen:
            raise ValueError(f"指数代码无效或重复：{code}")
        if not all(isinstance(item[k], str) and item[k].strip() for k in ("name", "category")):
            raise ValueError(f"指数 {code} 名称/类别为空")
        seen.add(code)
    return items


def normalize(frame: pd.DataFrame, code: str, start: date, end: date):
    missing = set(REQUIRED) - set(frame.columns)
    if missing:
        raise ValueError(f"指数 {code} 缺少列 {sorted(missing)}；接口列：{list(frame.columns)}")
    if frame.empty:
        raise ValueError(f"指数 {code} 无数据")
    raw = frame[REQUIRED].copy()
    raw["日期"] = pd.to_datetime(raw["日期"], errors="raise")
    raw["指数代码"] = raw["指数代码"].astype(str).str.replace(r"\.0$", "", regex=True)
    if not raw["指数代码"].eq(code).all():
        raise ValueError(f"指数 {code} 接口返回了不同代码")
    if raw["日期"].duplicated().any():
        raise ValueError(f"指数 {code} 存在重复日期")
    pe = pd.to_numeric(raw["滚动市盈率"], errors="raise")
    raw["滚动市盈率"] = pe
    raw = raw.loc[raw["日期"].dt.date.between(start, end)].sort_values("日期")
    if raw.empty or not raw["滚动市盈率"].notna().any():
        raise ValueError(f"指数 {code} 日期范围内无有效 PE")
    return raw


def fetch_all(config: Path, output: Path, years: int = 5, end: date | None = None, fetcher=None):
    if fetcher is None:
        import akshare as ak
        fetcher = getattr(ak, "index_hist_csindex", None)
        if fetcher is None:
            fetcher = getattr(ak, "stock_zh_index_hist_csindex")
    from dateutil.relativedelta import relativedelta
    end = end or date.today()
    start = end - relativedelta(years=years)
    items = load_config(config)
    result = {}
    for item in items:
        code = item["code"]
        LOG.info("获取 %s %s：%s 至 %s", code, item["name"], start, end)
        last_error = None
        for attempt in range(1, 4):
            try:
                frame = fetcher(symbol=code, start_date=start.strftime("%Y%m%d"), end_date=end.strftime("%Y%m%d"))
                clean = normalize(frame, code, start, end)
                rows = [{"date": r["日期"].strftime("%Y-%m-%d"), "pe": None if pd.isna(r["滚动市盈率"]) else float(r["滚动市盈率"])} for _, r in clean.iterrows()]
                valid_rows = [r for r in rows if r["pe"] is not None]
                result[code] = {**item, "rows": rows, "latest": valid_rows[-1]["date"], "valid": len(valid_rows)}
                LOG.info("指数 %s：%d 条，有效 PE %d 条，最新有效日期 %s", code, len(rows), result[code]["valid"], valid_rows[-1]["date"])
                break
            except Exception as exc:
                last_error = exc
                LOG.warning("%s 第 %d 次失败：%s", code, attempt, exc)
                if isinstance(exc, (AttributeError, ValueError, KeyError)):
                    raise RuntimeError(f"指数 {code} 接口字段/数据不匹配，停止重试：{exc}") from exc
                # 明确拒绝/限流时不重试，不更换身份、代理或来源规避限制。
                import requests
                cause = exc
                seen_causes = set()
                while cause is not None and id(cause) not in seen_causes:
                    seen_causes.add(id(cause))
                    status = (cause.response.status_code if isinstance(cause, requests.HTTPError) and cause.response is not None
                              else cause.code if isinstance(cause, urllib.error.HTTPError) else None)
                    if status in (401, 403, 429):
                        raise RuntimeError(f"指数 {code} 请求受限（HTTP {status}）；本次停止") from exc
                    cause = cause.__cause__ or cause.__context__
                if attempt < 3:
                    time.sleep((12, 30)[attempt - 1])
        else:
            raise RuntimeError(f"指数 {code} 连续失败：{last_error}") from last_error
        # 指数接口按清单串行，每个代码之间留出明显间隔。
        if item is not items[-1]:
            time.sleep(8)
    payload = {"generated_at": date.today().isoformat(), "start": start.isoformat(), "end": end.isoformat(), "indexes": result}
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix="valuation-", suffix=".json", dir=output.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        Path(temp).replace(output)
    finally:
        if Path(temp).exists():
            Path(temp).unlink()
    LOG.info("写入缓存 %s", output)


def main():
    parser = argparse.ArgumentParser(description="更新预设指数滚动市盈率")
    parser.add_argument("--config", type=Path, default=Path("valuation/indexes.json"))
    parser.add_argument("--output", type=Path, default=Path("data/valuation.json"))
    parser.add_argument("--years", type=int, default=5)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", handlers=[logging.StreamHandler(), logging.FileHandler("run.log", encoding="utf-8")])
    if not 1 <= args.years <= 30:
        parser.error("--years 必须为 1 至 30")
    try:
        fetch_all(args.config, args.output, args.years)
        return 0
    except Exception:
        LOG.exception("估值更新失败；不会写入不完整缓存")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
