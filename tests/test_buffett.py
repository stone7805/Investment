# -*- coding: utf-8 -*-
import json
import math
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from buffett.fetch import fetch_and_save, normalize
from buffett.build import build, check_payload
from build_portal import build as build_portal

ROOT = Path(__file__).resolve().parents[1]


def sample(count=46):
    days = pd.bdate_range("2026-10-19", periods=count)
    return pd.DataFrame({"日期": days, "总市值": [10000.0 + i * 10 for i in range(count)],
                         "GDP": [20000.0 for _ in range(count)], "收盘价": [3000.0] * count})


class BuffettTests(unittest.TestCase):
    def test_pctile_and_missing_window(self):
        raw = sample()
        raw.iloc[4, raw.columns.get_loc("总市值")] = 10000.0
        subset, stats = normalize(raw, today=date(2026, 12, 25))
        self.assertTrue(pd.isna(subset.iloc[0]["pctile_10y"]))
        self.assertTrue(pd.isna(subset.iloc[28]["pctile_10y"]))
        self.assertTrue(0 <= stats["latest_pct"] <= 100)
        self.assertAlmostEqual(stats["latest"], stats["latest_tmc"] / stats["latest_gdp"] * 100)
        self.assertEqual(stats["sample_count"], len(subset))

    def test_identical_duplicate_allowed_conflict_rejected(self):
        raw = sample()
        same = pd.concat([raw, raw.iloc[[1]]], ignore_index=True)
        sub, _ = normalize(same, today=date(2026, 12, 25))
        self.assertEqual(len(sub), len(raw))
        broken = raw.iloc[[1]].copy()
        broken["总市值"] += 20
        with self.assertRaisesRegex(ValueError, "冲突"):
            normalize(pd.concat([raw, broken]), today=date(2026, 12, 25))

    def test_invalid_and_future_rejected(self):
        for field, value in [("GDP", 0), ("总市值", float("inf")), ("总市值", None)]:
            with self.subTest(field=field, value=value):
                raw = sample()
                raw.loc[0, field] = value
                with self.assertRaises(ValueError):
                    normalize(raw, today=date(2026, 12, 25))
        with self.assertRaisesRegex(ValueError, "未来"):
            normalize(sample(), today=date(2026, 10, 19))
        with self.assertRaisesRegex(ValueError, "超过 14 天"):
            normalize(sample(), today=date(2027, 1, 31))

    def test_single_fetch_and_site_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            calls = []
            def fake_fetch():
                calls.append(1)
                return sample()
            source = root / "buffett.json"
            csv = root / "buffett.csv"
            payload = fetch_and_save(source, csv, fetcher=fake_fetch, today=date(2026, 12, 25))
            self.assertEqual(len(calls), 1)
            self.assertEqual(len(pd.read_csv(csv)), len(payload["rows"]))
            site = root / "docs/buffett.html"
            build(source, site)
            html = site.read_text(encoding="utf-8")
            self.assertIn('const D={', html)
            self.assertNotIn('/*__BUFFETT_DATA__*/{}', html)
            self.assertIn(payload["stats"]["latest_date"], html)
            corrupted = json.loads(source.read_text(encoding="utf-8"))
            corrupted["rows"][-1]["buffett"] = 999
            with self.assertRaisesRegex(ValueError, "不一致"):
                check_payload(corrupted)

    def test_portal_links_require_all_pages(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "docs/index.html"
            dest.parent.mkdir()
            for name in ("margin.html", "valuation.html", "buffett.html"):
                (dest.parent / name).write_text("<html></html>", encoding="utf-8")
            build_portal(ROOT / "portal_template.html", dest)
            text = dest.read_text(encoding="utf-8")
            for name in ("margin.html", "valuation.html", "buffett.html"):
                self.assertIn(f'href="{name}"', text)
            self.assertIn("待开发", text)
            (dest.parent / "buffett.html").unlink()
            with self.assertRaisesRegex(ValueError, "buffett.html"):
                build_portal(ROOT / "portal_template.html", dest)


if __name__ == "__main__":
    unittest.main()
