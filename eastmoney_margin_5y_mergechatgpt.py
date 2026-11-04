#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
抓取东方财富近五年融资融券数据，合并、计算比例及历史百分位，并导出 Excel。

直接运行：
    python eastmoney_margin_5y_merge.py

可选参数：
    python eastmoney_margin_5y_merge.py --years 5
    python eastmoney_margin_5y_merge.py --end-date 2026-07-25
    python eastmoney_margin_5y_merge.py --output 融资融券近五年合并分析.xlsx

依赖：
    python -m pip install -U pandas openpyxl

数据来源：
    https://data.eastmoney.com/rzrq/total.html
    https://data.eastmoney.com/rzrq/zhtjday.html
"""

from __future__ import annotations

import argparse
import json
import math
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime
from pathlib import Path
from typing import Any

try:
    import pandas as pd
    from openpyxl.formatting.rule import ColorScaleRule
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.worksheet.table import Table, TableStyleInfo
    from openpyxl.utils import get_column_letter
except ImportError as exc:
    missing_name = getattr(exc, "name", "pandas/openpyxl")
    print(f"缺少依赖：{missing_name}")
    print("请先执行：python -m pip install -U pandas openpyxl")
    raise SystemExit(1) from exc


API_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"
TOTAL_PAGE_URL = "https://data.eastmoney.com/rzrq/total.html"
ACCOUNT_PAGE_URL = "https://data.eastmoney.com/rzrq/zhtjday.html"
PAGE_SIZE = 500
MAX_RETRIES = 4

TOTAL_REPORT = {
    "report_name": "RPTA_RZRQ_LSHJ",
    "date_field": "DIM_DATE",
    "sort_field": "DIM_DATE",
    "referer": TOTAL_PAGE_URL,
}

ACCOUNT_REPORT = {
    "report_name": "RPTA_WEB_MARGIN_DAILYTRADE",
    "date_field": "STATISTICS_DATE",
    "sort_field": "STATISTICS_DATE",
    "referer": ACCOUNT_PAGE_URL,
}

# total.html 只保留用户指定的三列。
TOTAL_COLUMN_MAP = {
    "DIM_DATE": "交易日期",
    "NEW": "收盘-沪深300",
    "ZDF": "涨跌幅(%)-沪深300",
}

# zhtjday.html 接口返回的全部已知字段。若以后新增字段，程序也会原样保留。
ACCOUNT_COLUMN_MAP = {
    "STATISTICS_DATE": "交易日期",
    "DATE_MARK": "日期标记",
    "FIN_BALANCE": "融资余额(亿元)",
    "LOAN_BALANCE": "融券余额(亿元)",
    "MARGIN_BALANCE": "融资融券余额(亿元)",
    "BALANCE_RATIO": "融资融券余额占流通市值比(%)",
    "FIN_BUY_AMT": "融资买入额(亿元)",
    "LOAN_SELL_AMT": "融券卖出额(亿元)",
    "MARGIN_TRADE_AMT": "融资融券交易额(亿元)",
    "TRADE_AMT_RATIO": "融资融券交易额占A股成交额比(%)",
    "SECURITY_ORG_NUM": "证券公司数量(家)",
    "OPERATEDEPT_NUM": "营业部数量(家)",
    "PERSONAL_INVESTOR_NUM": "个人投资者数量(万名)",
    "ORG_INVESTOR_NUM": "机构投资者数量(家)",
    "INVESTOR_NUM": "参与交易的投资者数量(名)",
    "MARGINLIAB_INVESTOR_NUM": "有融资融券负债的投资者数量(名)",
    "FUND_MARKET_CAP": "担保资金(亿元)",
    "TOTAL_GUARANTEE": "担保物总价值(亿元)",
    "AVG_GUARANTEE_RATIO": "平均维持担保比例(%)",
    "SCI_CLOSE_PRICE": "收盘-上证指数(账户统计页)",
    "SCI_CHANGE_RATE": "涨跌幅(%)-上证指数(账户统计页)",
    # 东方财富接口字段本身拼写为 SUBSITUTION__CAP，程序不修改源字段。
    "SUBSITUTION__CAP": "可充抵保证金证券市值(亿元)",
}

CALCULATED_COLUMNS = [
    "当日融资买入额占融资余额比例",
    "当日融资买入额占融资余额比例近五年百分位",
    "当日参与交易投资者占有负债投资者比例",
    "当日参与交易投资者占有负债投资者比例近五年百分位",
    "当日平均维持担保比例近五年百分位",
]

PERCENT_POINT_COLUMNS = {
    "涨跌幅(%)-沪深300",
    "融资融券余额占流通市值比(%)",
    "融资融券交易额占A股成交额比(%)",
    "平均维持担保比例(%)",
    "涨跌幅(%)-上证指数(账户统计页)",
    *CALCULATED_COLUMNS,
}

INTEGER_COLUMNS = {
    "证券公司数量(家)",
    "营业部数量(家)",
    "机构投资者数量(家)",
    "参与交易的投资者数量(名)",
    "有融资融券负债的投资者数量(名)",
}

FIELD_DESCRIPTIONS = {
    "交易日期": "两张表按该日期进行一对一外连接；任一来源存在的数据都会保留。",
    "收盘-沪深300": "total.html 的沪深300收盘点位，源字段 NEW。",
    "涨跌幅(%)-沪深300": "total.html 的沪深300当日涨跌幅，单位为百分点，源字段 ZDF。",
    "日期标记": "zhtjday.html 接口原始字段 DATE_MARK。",
    "融资余额(亿元)": "zhtjday.html 的融资余额，单位亿元，源字段 FIN_BALANCE。",
    "融券余额(亿元)": "zhtjday.html 的融券余额，单位亿元，源字段 LOAN_BALANCE。",
    "融资融券余额(亿元)": "融资余额与融券余额合计，单位亿元，源字段 MARGIN_BALANCE。",
    "融资融券余额占流通市值比(%)": "接口原始百分数，单位为百分点，源字段 BALANCE_RATIO。",
    "融资买入额(亿元)": "当日融资买入额，单位亿元，源字段 FIN_BUY_AMT。",
    "融券卖出额(亿元)": "当日融券卖出额，单位亿元，源字段 LOAN_SELL_AMT。",
    "融资融券交易额(亿元)": "当日两融交易额，单位亿元，源字段 MARGIN_TRADE_AMT。",
    "融资融券交易额占A股成交额比(%)": "接口原始百分数，单位为百分点，源字段 TRADE_AMT_RATIO。",
    "证券公司数量(家)": "开展融资融券业务的证券公司数量，源字段 SECURITY_ORG_NUM。",
    "营业部数量(家)": "开展融资融券业务的营业部数量，源字段 OPERATEDEPT_NUM。",
    "个人投资者数量(万名)": "个人投资者数量，接口单位为万名，源字段 PERSONAL_INVESTOR_NUM。",
    "机构投资者数量(家)": "机构投资者数量，源字段 ORG_INVESTOR_NUM。",
    "参与交易的投资者数量(名)": "当日参与融资融券交易的投资者数量，源字段 INVESTOR_NUM。",
    "有融资融券负债的投资者数量(名)": "当日有融资融券负债的投资者数量，源字段 MARGINLIAB_INVESTOR_NUM。",
    "担保资金(亿元)": "担保资金，单位亿元，源字段 FUND_MARKET_CAP。",
    "可充抵保证金证券市值(亿元)": "可充抵保证金证券市值，单位亿元，源字段 SUBSITUTION__CAP。",
    "担保物总价值(亿元)": "担保物总价值，单位亿元，源字段 TOTAL_GUARANTEE。",
    "平均维持担保比例(%)": "接口原始百分数，单位为百分点，源字段 AVG_GUARANTEE_RATIO。",
    "收盘-上证指数(账户统计页)": "账户统计接口附带的上证指数收盘点位，源字段 SCI_CLOSE_PRICE。",
    "涨跌幅(%)-上证指数(账户统计页)": "账户统计接口附带的上证指数涨跌幅，单位为百分点，源字段 SCI_CHANGE_RATE。",
    "当日融资买入额占融资余额比例": "FIN_BUY_AMT ÷ FIN_BALANCE × 100，单位为百分点。",
    "当日融资买入额占融资余额比例近五年百分位": "该比例在本次近五年有效样本中的平均秩百分位。",
    "当日参与交易投资者占有负债投资者比例": "INVESTOR_NUM ÷ MARGINLIAB_INVESTOR_NUM × 100，单位为百分点。",
    "当日参与交易投资者占有负债投资者比例近五年百分位": "该比例在本次近五年有效样本中的平均秩百分位。",
    "当日平均维持担保比例近五年百分位": "AVG_GUARANTEE_RATIO 在本次近五年有效样本中的平均秩百分位。",
}


class EastmoneyDataError(RuntimeError):
    """东方财富接口数据不完整或结构发生变化。"""


def parse_iso_date(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"日期 {value!r} 无效，请使用 YYYY-MM-DD 格式。"
        ) from exc


def subtract_years(day: date, years: int) -> date:
    """按日历年回退；2 月 29 日遇到非闰年时改为 2 月 28 日。"""
    try:
        return day.replace(year=day.year - years)
    except ValueError:
        return day.replace(year=day.year - years, day=28)


def build_request(params: dict[str, Any], referer: str) -> urllib.request.Request:
    query = urllib.parse.urlencode(params)
    return urllib.request.Request(
        f"{API_URL}?{query}",
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/135.0 Safari/537.36"
            ),
            "Accept": "application/json,text/plain,*/*",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Referer": referer,
            "Connection": "close",
        },
        method="GET",
    )


def get_json(params: dict[str, Any], referer: str) -> dict[str, Any]:
    """使用标准库请求接口，并对临时网络错误自动重试。"""
    last_error: BaseException | None = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            request = build_request(params, referer)
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read()
            payload = json.loads(raw.decode("utf-8-sig"))

            if not isinstance(payload, dict):
                raise EastmoneyDataError("接口返回内容不是 JSON 对象。")
            if payload.get("success") is not True:
                message = payload.get("message") or payload.get("msg") or "未知错误"
                raise EastmoneyDataError(f"接口返回失败：{message}")
            if not isinstance(payload.get("result"), dict):
                raise EastmoneyDataError("接口返回中缺少 result 数据。")
            return payload

        except (
            urllib.error.HTTPError,
            urllib.error.URLError,
            TimeoutError,
            socket.timeout,
            json.JSONDecodeError,
        ) as exc:
            last_error = exc
            if attempt == MAX_RETRIES:
                break
            wait_seconds = 1.5 * (2 ** (attempt - 1))
            print(
                f"  第 {attempt} 次请求暂时失败：{exc}，"
                f"{wait_seconds:.1f} 秒后重试……"
            )
            time.sleep(wait_seconds)

    raise EastmoneyDataError(
        f"连续 {MAX_RETRIES} 次请求东方财富接口失败：{last_error}"
    ) from last_error


def fetch_report(
    report_name: str,
    date_field: str,
    sort_field: str,
    referer: str,
    start_date: date,
    end_date: date,
    display_name: str,
) -> pd.DataFrame:
    """分页下载一个报表，并在本地再次严格限定日期范围。"""
    base_params = {
        "reportName": report_name,
        "columns": "ALL",
        "source": "WEB",
        "client": "WEB",
        "sortColumns": sort_field,
        "sortTypes": "-1",
        "pageNumber": 1,
        "pageSize": PAGE_SIZE,
        "filter": f"({date_field}>='{start_date.isoformat()}')",
    }

    print(f"正在获取{display_name}……")
    first_payload = get_json(base_params, referer)
    first_result = first_payload["result"]
    pages = int(first_result.get("pages") or 1)
    expected_count = int(first_result.get("count") or 0)
    records = list(first_result.get("data") or [])
    print(
        f"  接口显示约 {expected_count} 条，"
        f"共 {pages} 页；正在下载第 1/{pages} 页"
    )

    for page_number in range(2, pages + 1):
        params = dict(base_params)
        params["pageNumber"] = page_number
        payload = get_json(params, referer)
        records.extend(payload["result"].get("data") or [])
        print(
            f"\r  正在下载第 {page_number}/{pages} 页，"
            f"已取得 {len(records)} 条",
            end="",
            flush=True,
        )
        time.sleep(0.15)
    if pages > 1:
        print()

    if not records:
        raise EastmoneyDataError(
            f"{display_name}在 {start_date} 至 {end_date} 范围内没有返回数据。"
        )

    frame = pd.DataFrame.from_records(records)
    if date_field not in frame.columns:
        raise EastmoneyDataError(
            f"{display_name}缺少日期字段 {date_field}；"
            f"当前字段为：{list(frame.columns)}"
        )

    parsed_dates = pd.to_datetime(frame[date_field], errors="coerce").dt.normalize()
    bad_date_count = int(parsed_dates.isna().sum())
    if bad_date_count:
        print(f"  警告：已丢弃 {bad_date_count} 条无法识别日期的记录。")
    frame[date_field] = parsed_dates
    frame = frame.loc[frame[date_field].notna()].copy()

    start_timestamp = pd.Timestamp(start_date)
    end_timestamp = pd.Timestamp(end_date)
    frame = frame.loc[
        frame[date_field].between(start_timestamp, end_timestamp, inclusive="both")
    ].copy()

    duplicate_count = int(frame.duplicated(date_field).sum())
    if duplicate_count:
        print(f"  警告：发现 {duplicate_count} 条重复日期，已保留接口排序后的第一条。")
        frame = frame.drop_duplicates(date_field, keep="first")

    frame = frame.sort_values(date_field, ascending=False).reset_index(drop=True)
    if frame.empty:
        raise EastmoneyDataError(
            f"{display_name}经日期清洗后没有可用记录。"
        )

    print(
        f"  有效记录 {len(frame)} 条，日期范围 "
        f"{frame[date_field].min():%Y-%m-%d} 至 "
        f"{frame[date_field].max():%Y-%m-%d}"
    )
    return frame


def require_columns(
    frame: pd.DataFrame, required: set[str], source_name: str
) -> None:
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise EastmoneyDataError(
            f"{source_name}缺少必要字段 {missing}；"
            f"当前字段为：{list(frame.columns)}"
        )


def to_numeric(frame: pd.DataFrame, columns: list[str]) -> None:
    for column in columns:
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")


def safe_ratio_percent(
    numerator: pd.Series, denominator: pd.Series
) -> pd.Series:
    """返回百分点数，例如 0.0612 输出为 6.12。"""
    denominator = pd.to_numeric(denominator, errors="coerce")
    numerator = pd.to_numeric(numerator, errors="coerce")
    result = numerator.div(denominator).mul(100)
    result = result.where(denominator.ne(0))
    return result.replace([math.inf, -math.inf], pd.NA).astype("Float64")


def percentile_rank(series: pd.Series) -> pd.Series:
    """
    计算全样本平均秩百分位。

    pandas 的 average rank 会对相同数值取其秩的平均值；
    pct=True 后结果范围为 (0, 1]，再乘 100 变为百分点。
    缺失值不参与样本，也保持为空。
    """
    numeric = pd.to_numeric(series, errors="coerce")
    return numeric.rank(method="average", pct=True, na_option="keep").mul(100)


def prepare_merged_data(
    total_raw: pd.DataFrame, account_raw: pd.DataFrame
) -> tuple[pd.DataFrame, list[dict[str, str]]]:
    require_columns(
        total_raw,
        set(TOTAL_COLUMN_MAP),
        "融资融券交易总量页",
    )
    require_columns(
        account_raw,
        {
            "STATISTICS_DATE",
            "FIN_BALANCE",
            "FIN_BUY_AMT",
            "INVESTOR_NUM",
            "MARGINLIAB_INVESTOR_NUM",
            "AVG_GUARANTEE_RATIO",
        },
        "融资融券账户统计页",
    )

    total = total_raw[list(TOTAL_COLUMN_MAP)].rename(columns=TOTAL_COLUMN_MAP).copy()

    # 保留账户统计接口返回的所有字段；已知字段改为中文，未来新增字段保留原名。
    account_source_fields = list(account_raw.columns)
    account_renames = {
        field: ACCOUNT_COLUMN_MAP.get(field, field) for field in account_source_fields
    }
    account = account_raw.rename(columns=account_renames).copy()

    numeric_account_fields = [
        field for field in account_source_fields if field != "STATISTICS_DATE"
    ]
    to_numeric(
        account,
        [account_renames[field] for field in numeric_account_fields],
    )
    to_numeric(total, ["收盘-沪深300", "涨跌幅(%)-沪深300"])

    # 外连接确保账户统计页的“所有数据”不会因另一张表更新稍慢而被丢弃。
    merged = account.merge(
        total,
        on="交易日期",
        how="outer",
        validate="one_to_one",
    )

    merged["当日融资买入额占融资余额比例"] = safe_ratio_percent(
        merged["融资买入额(亿元)"],
        merged["融资余额(亿元)"],
    )
    merged["当日融资买入额占融资余额比例近五年百分位"] = percentile_rank(
        merged["当日融资买入额占融资余额比例"]
    )

    merged["当日参与交易投资者占有负债投资者比例"] = safe_ratio_percent(
        merged["参与交易的投资者数量(名)"],
        merged["有融资融券负债的投资者数量(名)"],
    )
    merged["当日参与交易投资者占有负债投资者比例近五年百分位"] = (
        percentile_rank(merged["当日参与交易投资者占有负债投资者比例"])
    )

    merged["当日平均维持担保比例近五年百分位"] = percentile_rank(
        merged["平均维持担保比例(%)"]
    )

    # 用户指定的三项沪深300数据放最前，随后是账户统计全部字段和计算列。
    account_columns = [
        account_renames[field]
        for field in account_source_fields
        if field != "STATISTICS_DATE"
    ]
    ordered_columns = [
        "交易日期",
        "收盘-沪深300",
        "涨跌幅(%)-沪深300",
        *account_columns,
        *CALCULATED_COLUMNS,
    ]
    # 防止未来接口把字段名映射成重复列名。
    ordered_columns = list(dict.fromkeys(ordered_columns))
    merged = (
        merged[ordered_columns]
        .sort_values("交易日期", ascending=False)
        .reset_index(drop=True)
    )

    source_lookup = {
        **{chinese: source for source, chinese in TOTAL_COLUMN_MAP.items()},
        **{chinese: source for source, chinese in account_renames.items()},
    }
    dictionary_rows: list[dict[str, str]] = []
    for column in merged.columns:
        if column in CALCULATED_COLUMNS:
            source = "程序计算"
        elif column == "交易日期":
            source = "DIM_DATE / STATISTICS_DATE"
        else:
            source = source_lookup.get(column, column)
        dictionary_rows.append(
            {
                "输出列名": column,
                "来源字段": source,
                "说明": FIELD_DESCRIPTIONS.get(
                    column,
                    "东方财富账户统计接口返回的原始新增字段，程序未改名。",
                ),
            }
        )

    return merged, dictionary_rows


def add_excel_table(
    worksheet: Any, display_name: str, style_name: str = "TableStyleMedium2"
) -> None:
    if worksheet.max_row < 2 or worksheet.max_column < 1:
        return
    ref = f"A1:{get_column_letter(worksheet.max_column)}{worksheet.max_row}"
    table = Table(displayName=display_name, ref=ref)
    table.tableStyleInfo = TableStyleInfo(
        name=style_name,
        showFirstColumn=False,
        showLastColumn=False,
        showRowStripes=True,
        showColumnStripes=False,
    )
    worksheet.add_table(table)


def style_main_sheet(worksheet: Any) -> None:
    worksheet.freeze_panes = "A2"
    worksheet.sheet_view.showGridLines = False
    worksheet.auto_filter.ref = worksheet.dimensions
    worksheet.row_dimensions[1].height = 36

    header_fill = PatternFill("solid", fgColor="1F4E78")
    for cell in worksheet[1]:
        cell.fill = header_fill
        cell.font = Font(color="FFFFFF", bold=True)
        cell.alignment = Alignment(
            horizontal="center", vertical="center", wrap_text=True
        )

    header_to_column = {
        cell.value: cell.column for cell in worksheet[1] if cell.value is not None
    }
    for row in worksheet.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(vertical="center")

    date_column = header_to_column.get("交易日期")
    if date_column:
        for cell in worksheet.iter_cols(
            min_col=date_column,
            max_col=date_column,
            min_row=2,
            max_row=worksheet.max_row,
        ):
            for item in cell:
                item.number_format = "yyyy-mm-dd"

    for header, column_number in header_to_column.items():
        if header in PERCENT_POINT_COLUMNS:
            number_format = '0.00"%"'
        elif header in INTEGER_COLUMNS:
            number_format = "#,##0"
        elif header != "交易日期" and header != "日期标记":
            number_format = "#,##0.00"
        else:
            continue
        for cells in worksheet.iter_cols(
            min_col=column_number,
            max_col=column_number,
            min_row=2,
            max_row=worksheet.max_row,
        ):
            for cell in cells:
                cell.number_format = number_format

    for column_number, header_cell in enumerate(worksheet[1], start=1):
        header = str(header_cell.value or "")
        if header == "交易日期":
            width = 13
        elif "百分位" in header or "投资者" in header:
            width = 24
        elif len(header) >= 18:
            width = 22
        elif len(header) >= 12:
            width = 19
        else:
            width = 16
        worksheet.column_dimensions[get_column_letter(column_number)].width = width

    # 对三个百分位列添加红-黄-绿渐变，便于快速识别历史位置。
    for percentile_header in [
        "当日融资买入额占融资余额比例近五年百分位",
        "当日参与交易投资者占有负债投资者比例近五年百分位",
        "当日平均维持担保比例近五年百分位",
    ]:
        column_number = header_to_column.get(percentile_header)
        if column_number and worksheet.max_row >= 2:
            letter = get_column_letter(column_number)
            worksheet.conditional_formatting.add(
                f"{letter}2:{letter}{worksheet.max_row}",
                ColorScaleRule(
                    start_type="num",
                    start_value=0,
                    start_color="F8696B",
                    mid_type="num",
                    mid_value=50,
                    mid_color="FFEB84",
                    end_type="num",
                    end_value=100,
                    end_color="63BE7B",
                ),
            )

    add_excel_table(worksheet, "MarginMergedData")


def style_dictionary_sheet(worksheet: Any, table_name: str) -> None:
    worksheet.freeze_panes = "A2"
    worksheet.sheet_view.showGridLines = False
    worksheet.row_dimensions[1].height = 26
    header_fill = PatternFill("solid", fgColor="5B9BD5")

    for cell in worksheet[1]:
        cell.fill = header_fill
        cell.font = Font(color="FFFFFF", bold=True)
        cell.alignment = Alignment(horizontal="center", vertical="center")

    for row in worksheet.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=True)

    worksheet.column_dimensions["A"].width = 48
    worksheet.column_dimensions["B"].width = 34
    worksheet.column_dimensions["C"].width = 80
    add_excel_table(
        worksheet,
        table_name,
        style_name="TableStyleMedium9",
    )


def export_excel(
    merged: pd.DataFrame,
    dictionary_rows: list[dict[str, str]],
    output_path: Path,
    start_date: date,
    end_date: date,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    info_rows = [
        {"项目": "数据起始日期", "内容": start_date.isoformat()},
        {"项目": "数据结束日期", "内容": end_date.isoformat()},
        {"项目": "合并方式", "内容": "按交易日期一对一外连接，保留任一来源存在的日期。"},
        {
            "项目": "百分位口径",
            "内容": (
                "在本次日期范围内，对全部有效样本计算平均秩百分位；"
                "同值取平均秩，空值不参与。"
            ),
        },
        {"项目": "交易总量页", "内容": TOTAL_PAGE_URL},
        {"项目": "账户统计页", "内容": ACCOUNT_PAGE_URL},
    ]

    try:
        with pd.ExcelWriter(
            output_path,
            engine="openpyxl",
            date_format="yyyy-mm-dd",
            datetime_format="yyyy-mm-dd",
        ) as writer:
            merged.to_excel(writer, sheet_name="合并分析", index=False)
            pd.DataFrame(dictionary_rows).to_excel(
                writer, sheet_name="字段说明", index=False
            )
            pd.DataFrame(info_rows).to_excel(
                writer, sheet_name="运行说明", index=False
            )

            style_main_sheet(writer.book["合并分析"])
            style_dictionary_sheet(
                writer.book["字段说明"], "MarginFieldDictionary"
            )
            style_dictionary_sheet(
                writer.book["运行说明"], "MarginRunInformation"
            )

            writer.book["运行说明"].column_dimensions["A"].width = 24
            writer.book["运行说明"].column_dimensions["B"].width = 92
    except PermissionError as exc:
        raise PermissionError(
            f"无法写入 {output_path}。若文件正被 Excel 打开，请关闭后重试。"
        ) from exc


def validate_result(
    merged: pd.DataFrame,
    account_raw: pd.DataFrame,
    start_date: date,
    end_date: date,
) -> None:
    if merged.empty:
        raise EastmoneyDataError("合并结果为空。")
    if merged["交易日期"].duplicated().any():
        raise EastmoneyDataError("合并结果出现重复交易日期。")
    if not merged["交易日期"].between(
        pd.Timestamp(start_date), pd.Timestamp(end_date), inclusive="both"
    ).all():
        raise EastmoneyDataError("合并结果包含指定日期范围之外的数据。")

    # 外连接后，账户统计页每个有效日期都应保留。
    account_dates = set(account_raw["STATISTICS_DATE"].dropna())
    merged_dates = set(merged["交易日期"].dropna())
    if not account_dates.issubset(merged_dates):
        raise EastmoneyDataError("合并过程中丢失了账户统计页的日期。")

    for column in [
        "当日融资买入额占融资余额比例近五年百分位",
        "当日参与交易投资者占有负债投资者比例近五年百分位",
        "当日平均维持担保比例近五年百分位",
    ]:
        values = pd.to_numeric(merged[column], errors="coerce").dropna()
        if not values.between(0, 100, inclusive="both").all():
            raise EastmoneyDataError(f"{column} 出现 0—100 之外的数值。")

    check_rows = merged.dropna(
        subset=[
            "融资买入额(亿元)",
            "融资余额(亿元)",
            "当日融资买入额占融资余额比例",
        ]
    )
    if not check_rows.empty:
        row = check_rows.iloc[0]
        expected = row["融资买入额(亿元)"] / row["融资余额(亿元)"] * 100
        actual = row["当日融资买入额占融资余额比例"]
        if not math.isclose(float(actual), float(expected), rel_tol=1e-10):
            raise EastmoneyDataError("融资买入额占融资余额比例抽样校验失败。")


def build_parser() -> argparse.ArgumentParser:
    script_dir = Path(__file__).resolve().parent
    default_output = script_dir / "融资融券近五年合并分析.xlsx"

    parser = argparse.ArgumentParser(
        description="抓取并合并东方财富近五年融资融券数据，计算比例与百分位。"
    )
    parser.add_argument(
        "--years",
        type=int,
        default=5,
        help="回溯日历年数，默认 5。",
    )
    parser.add_argument(
        "--end-date",
        type=parse_iso_date,
        default=date.today(),
        metavar="YYYY-MM-DD",
        help="数据截止日期，默认今天。",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=default_output,
        help="输出 Excel 路径，默认保存在脚本同目录。",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if not 1 <= args.years <= 30:
        print("--years 必须在 1 到 30 之间。", file=sys.stderr)
        return 2

    end_date: date = args.end_date
    start_date = subtract_years(end_date, args.years)
    output_path: Path = args.output.expanduser()
    if output_path.suffix.lower() != ".xlsx":
        output_path = output_path.with_suffix(".xlsx")
    output_path = output_path.resolve()

    print("=" * 68)
    print("东方财富融资融券近五年合并分析")
    print(f"日期范围：{start_date} 至 {end_date}（含首尾日期）")
    print("=" * 68)

    try:
        total_raw = fetch_report(
            **TOTAL_REPORT,
            start_date=start_date,
            end_date=end_date,
            display_name="融资融券交易总量数据",
        )
        account_raw = fetch_report(
            **ACCOUNT_REPORT,
            start_date=start_date,
            end_date=end_date,
            display_name="融资融券账户统计数据",
        )

        print("正在合并数据并计算比例、近五年百分位……")
        merged, dictionary_rows = prepare_merged_data(total_raw, account_raw)
        validate_result(merged, account_raw, start_date, end_date)

        print("正在生成 Excel……")
        export_excel(
            merged,
            dictionary_rows,
            output_path,
            start_date,
            end_date,
        )

    except (EastmoneyDataError, OSError, ValueError, KeyError) as exc:
        print(f"\n运行失败：{exc}", file=sys.stderr)
        return 1

    account_rows = int(merged["融资余额(亿元)"].notna().sum())
    total_rows = int(merged["收盘-沪深300"].notna().sum())
    print("\n处理完成！")
    print(f"合并结果：{len(merged)} 行")
    print(f"其中账户统计有效行：{account_rows}；沪深300有效行：{total_rows}")
    print(f"输出文件：{output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
