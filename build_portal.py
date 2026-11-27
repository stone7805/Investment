#!/usr/bin/env python3
"""生成门户首页；构建顺序应在两类页面验证通过之后。"""
import argparse
import logging
from pathlib import Path


def build(source: Path, target: Path):
    text = source.read_text(encoding="utf-8")
    for page in ("margin.html", "valuation.html", "buffett.html"):
        if f'href="{page}"' not in text or not (target.parent / page).is_file():
            raise ValueError(f"门户模块链接或页面缺失：{page}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    logging.info("生成门户 %s", target)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=Path("portal_template.html"))
    parser.add_argument("--output", type=Path, default=Path("docs/index.html"))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", handlers=[logging.StreamHandler(), logging.FileHandler("run.log", encoding="utf-8")])
    try:
        build(args.input, args.output)
        return 0
    except Exception:
        logging.exception("门户生成失败")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
