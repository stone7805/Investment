# -*- coding: utf-8 -*-
"""
中国大陆巴菲特指标（Buffett Indicator）绘制程序 v2
----------------------------------------------------
含义：
    巴菲特指标 = 股票市场总市值(TMC) / 国内生产总值(GDP) × 100%
    国内常用口径 —— A股总市值 / 上年度名义 GDP。

数据源（一次性，稳定）：
    akshare.stock_buffett_index_lg()
        乐咕乐股-底部研究-巴菲特指标
        无参数；单次返回全历史（约 2005-04 至今）。
        返回列：
            日期        交易日
            收盘价      上证综指收盘价
            总市值      A 股总市值（亿元）
                       = A 股收盘价 × 已发行股票总股本(含 A 股/B 股/H 股)
            GDP         上年度国内生产总值（亿元；年度值，跨年会跳变）
            近十年分位数 该日 "总市值/GDP" 在近十年历史上的分位
            总历史分位数 该日 "总市值/GDP" 在全历史上的分位

日志：
    stdout + 同目录下 buffett_indicator.log
    每一步都会打印；出错时把日志文件贴给我，可以直接定位。

依赖：
    pip install akshare pandas numpy matplotlib
"""

import os
import sys
import logging
import traceback

import numpy as np
import pandas as pd

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# ------------------------------------------------------------
# 0. 配置
# ------------------------------------------------------------
YEARS_BACK = 10
OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE   = os.path.join(OUTPUT_DIR, "buffett_indicator.log")
CSV_FILE   = os.path.join(OUTPUT_DIR, "buffett_indicator_data.csv")
PNG_FILE   = os.path.join(OUTPUT_DIR, "buffett_indicator.png")


# ------------------------------------------------------------
# 1. 日志
# ------------------------------------------------------------
def setup_logger() -> logging.Logger:
    logger = logging.getLogger("buffett")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()

    fmt = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    fh = logging.FileHandler(LOG_FILE, mode="w", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    return logger


log = setup_logger()


# ------------------------------------------------------------
# 2. 拉取巴菲特指标全历史数据
# ------------------------------------------------------------
def fetch_buffett_data() -> pd.DataFrame:
    import akshare as ak
    log.info("开始拉取巴菲特指标数据 (akshare.stock_buffett_index_lg) ...")

    df = ak.stock_buffett_index_lg()
    log.debug("原始列: %s", list(df.columns))
    log.debug("原始前3行:\n%s", df.head(3))
    log.debug("原始后3行:\n%s", df.tail(3))
    log.info("接口返回记录数: %d", len(df))

    # 字段容错映射
    col_map = {}
    for c in df.columns:
        cl = str(c).strip()
        if cl in ("日期", "date"):
            col_map[c] = "date"
        elif cl in ("总市值",):
            col_map[c] = "tmc"
        elif cl in ("GDP", "gdp"):
            col_map[c] = "gdp"
        elif "近十年" in cl or "近10年" in cl or "recent10" in cl.lower():
            col_map[c] = "pctile_10y"
        elif "总历史" in cl or "全历史" in cl or "allhistory" in cl.lower():
            col_map[c] = "pctile_all"
        elif cl in ("收盘价", "close"):
            col_map[c] = "close"
    df = df.rename(columns=col_map)

    required = {"date", "tmc", "gdp"}
    missing = required - set(df.columns)
    if missing:
        raise RuntimeError(
            f"接口返回缺少必要字段 {missing}，实际列: {list(df.columns)}"
        )

    df["date"] = pd.to_datetime(df["date"])
    df["tmc"] = pd.to_numeric(df["tmc"], errors="coerce")
    df["gdp"] = pd.to_numeric(df["gdp"], errors="coerce")
    df = df.dropna(subset=["date", "tmc", "gdp"]).sort_values("date").reset_index(drop=True)

    df["buffett"] = df["tmc"] / df["gdp"] * 100.0

    if "pctile_10y" in df.columns:
        p = pd.to_numeric(df["pctile_10y"], errors="coerce")
        pmax = p.dropna().max()
        if pd.notna(pmax) and pmax <= 1.5:
            df["pctile_10y"] = p * 100.0
            log.info("接口 '近十年分位数' 单位识别为 0~1，已转成 %%")
        else:
            df["pctile_10y"] = p
            log.info("接口 '近十年分位数' 单位识别为 0~100，直接使用")
    else:
        log.warning("接口未返回 '近十年分位数' 列，将在后续自算 expanding 分位")
        df["pctile_10y"] = np.nan

    log.info("原始序列区间: %s ~ %s",
             df["date"].min().date(), df["date"].max().date())
    log.info("巴菲特指标范围: %.2f%% ~ %.2f%%",
             df["buffett"].min(), df["buffett"].max())
    return df[["date", "tmc", "gdp", "buffett", "pctile_10y"]]


# ------------------------------------------------------------
# 3. 截取近 N 年 & 计算参考水平线
# ------------------------------------------------------------
def slice_and_stats(df: pd.DataFrame, years: int):
    end_d   = df["date"].max()
    start_d = end_d - pd.DateOffset(years=years)
    log.info("截取近 %d 年数据: %s ~ %s",
             years, start_d.date(), end_d.date())

    sub = df[df["date"] >= start_d].copy().reset_index(drop=True)
    log.info("近 %d 年样本数: %d", years, len(sub))

    if sub["pctile_10y"].isna().any():
        log.info("使用 expanding 方法自算近十年分位数以补齐缺失")

        def _pctile(x: pd.Series) -> float:
            cur = x.iloc[-1]
            return (x <= cur).mean() * 100.0

        sub["pctile_10y"] = sub["buffett"].expanding(min_periods=30).apply(_pctile, raw=False)

    stats = {
        "mean":   float(sub["buffett"].mean()),
        "p90":    float(sub["buffett"].quantile(0.90)),
        "p10":    float(sub["buffett"].quantile(0.10)),
        "median": float(sub["buffett"].median()),
        "latest":     float(sub["buffett"].iloc[-1]),
        "latest_pct": float(sub["pctile_10y"].iloc[-1]),
        "latest_date": sub["date"].iloc[-1],
    }
    log.info("近 %d 年统计 — 均值=%.2f%%  中位=%.2f%%  90分位=%.2f%%  10分位=%.2f%%",
             years, stats["mean"], stats["median"], stats["p90"], stats["p10"])
    log.info("最新一日 (%s): 巴菲特指标=%.2f%%  近十年分位=%.2f%%",
             stats["latest_date"].date(), stats["latest"], stats["latest_pct"])
    return sub, stats


# ------------------------------------------------------------
# 4. 绘图
# ------------------------------------------------------------
def plot_buffett(df: pd.DataFrame, stats: dict, png_path: str) -> None:
    log.info("开始绘图 -> %s", png_path)

    from matplotlib import font_manager
    zh_font = None
    for name in ["Microsoft YaHei", "SimHei", "Noto Sans CJK SC",
                 "Source Han Sans CN", "PingFang SC", "WenQuanYi Zen Hei",
                 "Arial Unicode MS"]:
        try:
            if any(name.lower() in f.name.lower() for f in font_manager.fontManager.ttflist):
                zh_font = name
                break
        except Exception:
            pass

    if zh_font:
        plt.rcParams["font.sans-serif"] = [zh_font]
        plt.rcParams["axes.unicode_minus"] = False
        log.info("使用中文字体: %s", zh_font)
        L_TITLE  = f"中国大陆巴菲特指标（近{YEARS_BACK}年，A股总市值 / GDP）"
        L_LEFT   = "巴菲特指标 TMC/GDP (%)"
        L_RIGHT  = "巴菲特指标 近十年百分位 (%)"
        L_MEAN, L_P90, L_P10 = "均值", "90% 分位", "10% 分位"
        L_MAIN, L_PCT, L_XLABEL = "巴菲特指标", "近十年百分位", "日期"
    else:
        log.warning("未找到中文字体，改用英文标签（不影响数据）")
        L_TITLE  = f"China Buffett Indicator (Last {YEARS_BACK} Years, TMC/GDP)"
        L_LEFT   = "Buffett Indicator TMC/GDP (%)"
        L_RIGHT  = "10Y Historical Percentile (%)"
        L_MEAN, L_P90, L_P10 = "Mean", "90th Pctile", "10th Pctile"
        L_MAIN, L_PCT, L_XLABEL = "Buffett Indicator", "Percentile", "Date"

    fig, ax1 = plt.subplots(figsize=(13, 6.5))
    ax2 = ax1.twinx()

    ax1.plot(df["date"], df["buffett"], color="#1f77b4", lw=1.6, label=L_MAIN)
    ax1.set_xlabel(L_XLABEL)
    ax1.set_ylabel(L_LEFT, color="#1f77b4")
    ax1.tick_params(axis="y", labelcolor="#1f77b4")

    ax1.axhline(stats["mean"], color="#555555", ls="--", lw=1,
                label=f"{L_MEAN}: {stats['mean']:.1f}%")
    ax1.axhline(stats["p90"],  color="#d62728", ls="--", lw=1,
                label=f"{L_P90}: {stats['p90']:.1f}%")
    ax1.axhline(stats["p10"],  color="#2ca02c", ls="--", lw=1,
                label=f"{L_P10}: {stats['p10']:.1f}%")

    ax2.plot(df["date"], df["pctile_10y"], color="#ff7f0e",
             lw=1.2, alpha=0.75, label=L_PCT)
    ax2.set_ylabel(L_RIGHT, color="#ff7f0e")
    ax2.tick_params(axis="y", labelcolor="#ff7f0e")
    ax2.set_ylim(0, 100)

    ax1.set_title(L_TITLE, fontsize=15, pad=12)
    ax1.grid(True, ls=":", alpha=0.4)

    h1, l1 = ax1.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax1.legend(h1 + h2, l1 + l2, loc="upper left", framealpha=0.9)

    # 最新一日标注
    ax1.scatter([stats["latest_date"]], [stats["latest"]],
                s=45, color="#1f77b4", zorder=5)
    ax1.annotate(
        f"{stats['latest']:.1f}%\n({stats['latest_date'].strftime('%Y-%m-%d')})",
        xy=(stats["latest_date"], stats["latest"]),
        xytext=(-70, 18), textcoords="offset points",
        fontsize=9, color="#1f77b4",
        arrowprops=dict(arrowstyle="->", color="#1f77b4", lw=0.8),
    )

    fig.tight_layout()
    fig.savefig(png_path, dpi=140)
    plt.close(fig)
    log.info("图像已保存: %s", png_path)


# ------------------------------------------------------------
# 5. 主流程
# ------------------------------------------------------------
def main() -> int:
    log.info("=" * 60)
    log.info("巴菲特指标程序启动 (v2)")
    log.info("=" * 60)

    try:
        import akshare as ak
        log.info("akshare 版本: %s", ak.__version__)
    except ImportError:
        log.error("未安装 akshare，请先执行:  pip install akshare --upgrade")
        return 1
    except Exception:
        log.error("导入 akshare 失败:\n%s", traceback.format_exc())
        return 1

    try:
        raw_df = fetch_buffett_data()
    except Exception:
        log.error("拉取巴菲特指标数据失败:\n%s", traceback.format_exc())
        return 2

    if raw_df.empty:
        log.error("接口返回空数据")
        return 3

    try:
        sub_df, stats = slice_and_stats(raw_df, YEARS_BACK)
    except Exception:
        log.error("统计阶段失败:\n%s", traceback.format_exc())
        return 4

    if sub_df.empty:
        log.error("近 %d 年样本为空", YEARS_BACK)
        return 5

    try:
        out = sub_df.rename(columns={
            "date":       "日期",
            "tmc":        "A股总市值(亿元)",
            "gdp":        "GDP上年度(亿元)",
            "buffett":    "巴菲特指标(%)",
            "pctile_10y": "近十年百分位(%)",
        })
        out.to_csv(CSV_FILE, index=False, encoding="utf-8-sig")
        log.info("明细数据已保存: %s", CSV_FILE)
    except Exception:
        log.warning("保存 CSV 失败（不影响绘图）:\n%s", traceback.format_exc())

    try:
        plot_buffett(sub_df, stats, PNG_FILE)
    except Exception:
        log.error("绘图失败:\n%s", traceback.format_exc())
        return 6

    log.info("-" * 60)
    log.info("完成 ✅  输出目录: %s", OUTPUT_DIR)
    log.info("  图像:   %s", PNG_FILE)
    log.info("  数据:   %s", CSV_FILE)
    log.info("  日志:   %s", LOG_FILE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
