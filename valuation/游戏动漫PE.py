# -*- coding: utf-8 -*-
import akshare as ak
import pandas as pd
from datetime import datetime
from dateutil.relativedelta import relativedelta

def fetch_hist_pe_data(index_code, start_date, end_date, save_path=None):
    """
    从 csindex.com.cn 获取指定指数的历史滚动市盈率数据

    Parameters:
        index_code: str, 指数代码，如 "930901"
        start_date: str, 起始日期 YYYYMMDD，如 "20210601"
        end_date: str, 结束日期 YYYYMMDD，如 "20260710"
        save_path: str, 可选，CSV 保存路径，如 "csi_930901_pe_data.csv"

    Returns:
        pd.DataFrame，包含日期、指数代码、指数中文名称、滚动市盈率等字段
    """
    print(f"正在获取指数 {index_code} 从 {start_date} 至 {end_date} 的数据...")

    try:
        # 调用 AKShare 中证指数日频数据接口
        df = ak.stock_zh_index_hist_csindex(
            symbol=index_code,
            start_date=start_date,
            end_date=end_date
        )
    except Exception as e:
        print(f"数据获取失败: {e}")
        print("可能原因：未安装 akshare，或指数代码/日期格式有误。")
        return None

    if df.empty:
        print("未获取到数据，请检查指数代码或日期范围是否正确。")
        return None

    # 重命名列名便于阅读（原始列名中通常包含中文名称）
    # 核心列：日期, 指数代码, 指数中文简称, 滚动市盈率
    pe_columns = ['日期', '指数代码', '指数中文简称', '滚动市盈率']
    existing_columns = [col for col in pe_columns if col in df.columns]
    result_df = df[existing_columns].copy()

    # 剔除滚动市盈率为空的行
    result_df = result_df.dropna(subset=['滚动市盈率']).reset_index(drop=True)

    # 打印基础统计信息
    print(f"\n成功获取 {len(result_df)} 个交易日的 PE 数据")
    print(f"时间范围: {result_df['日期'].min()} 至 {result_df['日期'].max()}")
    print(f"近五年 PE 平均值: {result_df['滚动市盈率'].mean():.2f}")
    print(f"近五年 PE 最大值: {result_df['滚动市盈率'].max():.2f}")
    print(f"近五年 PE 最小值: {result_df['滚动市盈率'].min():.2f}")

    # 可选：保存为 CSV 文件
    if save_path:
        result_df.to_csv(save_path, index=False, encoding='utf-8-sig')
        print(f"\n数据已保存至: {save_path}")

    return result_df


if __name__ == "__main__":
    # 配置参数
    INDEX_CODE = "930901"                     # 中证动漫游戏指数代码
    START_DATE = "20210611"                   # 近五年的起始日期（可自行修改）
    END_DATE = datetime.now().strftime("%Y%m%d")   # 当前日期
    SAVE_PATH = "csi_930901_pe_data.csv"      # 保存的 CSV 文件名（可选，不填则不保存）

    # 执行爬取
    pe_data = fetch_hist_pe_data(
        index_code=INDEX_CODE,
        start_date=START_DATE,
        end_date=END_DATE,
        save_path=SAVE_PATH
    )

    # 显示前5行示例
    if pe_data is not None:
        print("\n前5行数据预览：")
        print(pe_data.head())