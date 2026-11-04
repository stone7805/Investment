import tempfile
import unittest
from pathlib import Path

import pandas as pd

from build_site import COLUMNS, build
from eastmoney_margin_5y_mergechatgpt import percentile_rank, safe_ratio_percent


class ProjectTests(unittest.TestCase):
    def test_ratio_and_percentile(self):
        ratio = safe_ratio_percent(pd.Series([6, 0]), pd.Series([100, 0]))
        self.assertAlmostEqual(float(ratio.iloc[0]), 6.0)
        self.assertTrue(pd.isna(ratio.iloc[1]))
        rank = percentile_rank(pd.Series([2, 2, 4]))
        self.assertAlmostEqual(rank.iloc[0], 50.0)
        self.assertAlmostEqual(rank.iloc[2], 100.0)

    def test_build_site(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = []
            for day in ["2026-11-02", "2026-11-03"]:
                row = {column: 42.0 for column in COLUMNS}
                row["交易日期"] = day
                rows.append(row)
            source = root / "sample.xlsx"
            pd.DataFrame(rows).to_excel(source, sheet_name="合并分析", index=False)
            target = root / "index.html"
            build(source, target)
            html = target.read_text(encoding="utf-8")
            self.assertIn("2026-11-03", html)
            self.assertIn("const D=[", html)
            self.assertNotIn("/*__DATA__*/[]", html)


if __name__ == "__main__":
    unittest.main()
