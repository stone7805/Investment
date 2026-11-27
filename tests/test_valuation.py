import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

import pandas as pd

from valuation.build import build
from valuation.fetch import load_config, normalize, fetch_all


class ValuationTests(unittest.TestCase):
    def test_config(self):
        items = load_config(Path(__file__).resolve().parents[1] / "valuation/indexes.json")
        self.assertEqual(len(items), 3)
        self.assertEqual(items[0]["code"], "930901")

    def test_normalize(self):
        frame = pd.DataFrame({"日期": ["2026-11-03", "2026-11-02"], "指数代码": ["930901", "930901"], "指数中文简称": ["动漫游戏", "动漫游戏"], "滚动市盈率": [28.5, 29.2]})
        clean = normalize(frame, "930901", date(2026, 1, 1), date(2026, 11, 5))
        self.assertEqual(len(clean), 2)
        self.assertEqual(clean.iloc[0]["滚动市盈率"], 29.2)

    def test_fetch_serial_and_latest_nonnull(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            config = root / "list.json"
            config.write_text(json.dumps([{"code": "930901", "name": "动漫游戏", "category": "主题"}], ensure_ascii=False), encoding="utf-8")
            called = []
            def fake_fetcher(**kwargs):
                called.append(kwargs)
                return pd.DataFrame({"日期": ["2026-11-02", "2026-11-03"],
                                     "指数代码": ["930901", "930901"],
                                     "指数中文简称": ["动漫游戏", "动漫游戏"],
                                     "滚动市盈率": [28.5, None]})
            path = root / "valuation.json"
            fetch_all(config, path, 5, date(2026, 11, 4), fetcher=fake_fetcher)
            result = json.loads(path.read_text(encoding="utf-8"))["indexes"]["930901"]
            self.assertEqual(len(called), 1)
            self.assertEqual(result["latest"], "2026-11-02")
            self.assertEqual(result["valid"], 1)

    def test_build_and_navigation(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "data.json"
            source.write_text(json.dumps({"indexes": {"930901": {"code": "930901", "name": "中证动漫游戏", "category": "主题指数", "rows": [{"date": "2026-11-03", "pe": 28.5}]}}}, ensure_ascii=False), encoding="utf-8")
            out = root / "valuation.html"
            build(source, out)
            self.assertIn("中证动漫游戏", out.read_text(encoding="utf-8"))
            portal = (Path(__file__).resolve().parents[1] / "portal_template.html").read_text(encoding="utf-8")
            self.assertIn('href="margin.html"', portal)
            self.assertIn('href="valuation.html"', portal)


if __name__ == "__main__":
    unittest.main()
