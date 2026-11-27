import tempfile
import unittest
from pathlib import Path

import pandas as pd

from build_site import COLUMNS, build
from eastmoney_margin_5y_mergechatgpt import (
    EastmoneyDataError, percentile_rank, prepare_merged_data, safe_ratio_percent,
    validate_result,
)
from datetime import date


class ProjectTests(unittest.TestCase):
    def test_ratio_and_percentile(self):
        ratio = safe_ratio_percent(pd.Series([6, 0]), pd.Series([100, 0]))
        self.assertAlmostEqual(float(ratio.iloc[0]), 6.0)
        self.assertTrue(pd.isna(ratio.iloc[1]))
        rank = percentile_rank(pd.Series([2, 2, 4]))
        self.assertAlmostEqual(rank.iloc[0], 50.0)
        self.assertAlmostEqual(rank.iloc[2], 100.0)

    def test_missing_nullable_ratio_has_no_percentile(self):
        ratio = pd.Series([pd.NA, 5.8, 6.2], dtype="Float64")
        ranks = percentile_rank(ratio)
        self.assertTrue(pd.isna(ranks.iloc[0]))
        self.assertAlmostEqual(float(ranks.iloc[1]), 50.0)
        self.assertAlmostEqual(float(ranks.iloc[2]), 100.0)
        self.assertTrue(percentile_rank(pd.Series([pd.NA], dtype="Float64")).isna().all())
        self.assertTrue(percentile_rank(pd.Series([], dtype="Float64")).empty)

    def test_outer_join_new_index_date_does_not_invent_rank(self):
        total = pd.DataFrame({"DIM_DATE": pd.to_datetime(["2026-11-11", "2026-11-10"]),
                              "NEW": [4076, 4060], "ZDF": [0.4, 0.2]})
        account = pd.DataFrame({"STATISTICS_DATE": pd.to_datetime(["2026-11-10"]),
                                "FIN_BALANCE": [22656.5], "FIN_BUY_AMT": [1318.6],
                                "MARGIN_BALANCE": [22700.0],
                                "INVESTOR_NUM": [200], "MARGINLIAB_INVESTOR_NUM": [1000],
                                "AVG_GUARANTEE_RATIO": [220]})
        merged, _ = prepare_merged_data(total, account)
        validate_result(merged, account, date(2026, 11, 9), date(2026, 11, 11))
        latest = merged.loc[merged["交易日期"] == pd.Timestamp("2026-11-11")].iloc[0]
        self.assertTrue(pd.isna(latest["当日融资买入额占融资余额比例"]))
        self.assertTrue(pd.isna(latest["当日融资买入额占融资余额比例近五年百分位"]))
        self.assertEqual(latest["收盘-沪深300"], 4076)
        broken = merged.copy()
        broken.loc[broken["交易日期"] == pd.Timestamp("2026-11-11"),
                   "当日融资买入额占融资余额比例近五年百分位"] = 0.1
        with self.assertRaises(EastmoneyDataError):
            validate_result(broken, account, date(2026, 11, 9), date(2026, 11, 11))

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
            # 二次门禁：基础值为空但百分位有值时，网页不能发布。
            rows[1]["当日融资买入额占融资余额比例"] = None
            pd.DataFrame(rows).to_excel(source, sheet_name="合并分析", index=False)
            with self.assertRaisesRegex(ValueError, "缺失日期不一致"):
                build(source, target)


if __name__ == "__main__":
    unittest.main()
