#!/usr/bin/env python3
"""将已获取的指数 PE 缓存嵌入静态估值页面。"""
import argparse
import json
import logging
from pathlib import Path

LOG = logging.getLogger("valuation-build")


def build(source: Path, target: Path, template: Path | None = None):
    payload = json.loads(source.read_text(encoding="utf-8"))
    indexes = payload.get("indexes")
    if not isinstance(indexes, dict) or not indexes:
        raise ValueError("估值缓存无指数")
    for code, item in indexes.items():
        rows = item.get("rows", [])
        if not rows or not any(r.get("pe") is not None for r in rows):
            raise ValueError(f"{code} 无有效数据")
        if rows != sorted(rows, key=lambda x: x["date"]):
            raise ValueError(f"{code} 日期顺序不正确")
    template = template or Path(__file__).resolve().parent / "template.html"
    html = template.read_text(encoding="utf-8")
    marker = "/*__VALUATION__*/{}"
    if html.count(marker) != 1:
        raise ValueError("估值模板缺少唯一数据占位符")
    inline = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":")).replace("<", "\\u003c")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(html.replace(marker, inline), encoding="utf-8")
    LOG.info("已生成估值页 %s；指数 %d 个", target, len(indexes))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=Path("data/valuation.json"))
    parser.add_argument("--output", type=Path, default=Path("docs/valuation.html"))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", handlers=[logging.StreamHandler(), logging.FileHandler("run.log", encoding="utf-8")])
    try:
        build(args.input, args.output)
        return 0
    except Exception:
        LOG.exception("估值页生成失败")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
