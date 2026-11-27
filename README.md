# 数据观察｜两融、板块估值与巴菲特指标

面向 GitHub Pages 的静态数据门户。首页依次进入 **两融观察**、**板块估值**、**巴菲特指标**，并预留行业景气、风险指标和研究工具三个待开发模块。公开页面只展示已校验的数据；不是实时行情终端，也不构成投资建议。

## 本次升级要点

| 模块 | 页面 | 来源与日期 | 可见内容 |
| --- | --- | --- | --- |
| 两融观察 | `docs/margin.html` | 东方财富两路接口；每项指标标注自身最后有效日 | 融资余额、买入强度、沪深300、历史百分位与趋势 |
| 板块估值 | `docs/valuation.html` | AKShare 中证指数日频接口 `index_hist_csindex` | 预设代码检索、滚动 PE 趋势/分布/样本排名 |
| 巴菲特指标 | `docs/buffett.html` | AKShare/乐咕乐股 `stock_buffett_index_lg`；一次返回全历史 | A 股总市值/上年度名义 GDP、十年滚动百分位、三张交互图 |
| 门户 | `docs/index.html` | 指向上述三个独立页面 | 模块入口及三个明确标为“待开发”的位置 |

源程序 `buffett/buffett_indicator_china_original.py` 为用户上传稿，保留作口径参照；门户更新采用 `buffett/fetch.py` 与 `buffett/build.py`，不运行原脚本的 PNG 绘图逻辑。

### 巴菲特指标口径

- 比率 = A 股总市值（亿元）÷ 接口返回的**上年度名义 GDP**（亿元）× 100。年度 GDP 是阶段性分母，不是当季 GDP；跨年换值可能出现跳变。
- 每个日期的十年百分位均以该日向前十个日历年（含首尾）的有效比率为样本，同值使用平均秩；有效样本少于 30 日时显示空白。接口目前只给出“日期、收盘价、总市值、GDP”，**没有原脚本描述的近十年百分位列**，故改为本地明确计算。
- 接口中同一日期完全重复的记录只计一次，冲突日期、非正 GDP/市值、未来日期或非有限数会报错；源站连续超过 14 天未给出新日期也会暂停此次部署。本地实测 8 条完全相同的重复日期。数据日期和百分位样本数在页面中直接显示；不把页面构建日当数据日。
- 股票市场与经济总量口径受源站修订影响，百分位只是历史位置，不代表统一的高低估阈值。

## 升级已在用的 GitHub 仓库

**不要上传 ZIP 文件本身。** 先备份你当前仓库的关键文件和可访问的 Pages 地址。在 GitHub 网页上传本项目 ZIP *内部*文件，保持仓库根目录结构；如果 GitHub 上传界面不能保留文件夹，可逐级上传并核对 `.github/workflows/update.yml`、`buffett/`、`valuation/`、`tests/`、`docs/` 路径。请勿覆盖无关文件。

此升级会将原 `docs/index.html` 两融首页换为**门户首页**，原两融页移动到 `docs/margin.html`。新入口是原 Pages 地址，旧首页直达两融的书签需改为 `/margin.html`。保留相同路径 `.github/workflows/update.yml` 作为唯一部署工作流，避免两套工作流竞争。首次上传时包内的 `docs/` 是**本地校验用预览**（来源日期以页面标注为准），请在分享网址前手动运行一次 Actions 并核实部署步骤绿色。

操作步骤：

1. 仓库 `Settings → Pages → Source` 保持 **GitHub Actions**。
2. 在仓库根目录上传或更新 ZIP 内所有文件和目录；`.github` 是隐藏目录，提交后确认它存在。
3. `Actions → 更新数据观察门户 → Run workflow` 手动运行，检查“两融抓取”“指数估值抓取”“巴菲特指标抓取”“13 项以上测试”和 `deploy-pages` 均成功，再访问原 Pages 地址。每日凌晨/早盘数据可滞后，以页面最新有效日期为准。
4. 若单个源站接口不通或限流，本次不会部署不完整门户，线上保留上次成功页面。运行记录中的 **Artifacts** 保存 Excel、估值 JSON、巴菲特 JSON/CSV 和 `run.log`（90 天）。

## 低频顺序请求与限制

工作流默认在**北京时间工作日 09:15**触发一次（UTC `15 1 * * 1-5`）；GitHub 调度不保证准点。为了降低请求密度：两融接口分页串行、页间至少 3 秒；模块之间各等待 20 秒；估值清单按顺序抓取，每只指数间隔 8 秒；巴菲特指标**只发一次全历史请求**。临时网络错误有限次数退避；当能明确识别 401/403/429 限流错误时停止本次更新，不通过伪装身份、换代理或高频重试绕过。**这些措施只能减小负载，不能保证不会被源站限制。**

估值页仅查询 `valuation/indexes.json` 中已成功抓取的中证指数代码。目前示例含 930901（动漫游戏）、931140（医药50）、931454（港股通消费）。输入新代码不会直接联网；要新增支持的指数，先扩清单、核对数据源是否返回“滚动市盈率”，再运行工作流。AKShare 升级可能变更函数名或字段，本项目已经兼容当前 `index_hist_csindex`；接口更改时会明确失败而非虚构数值。

## 本地运行

在项目根目录安装依赖后按**顺序**运行：

```bash
python -m pip install -r requirements.txt
python eastmoney_margin_5y_mergechatgpt.py --years 5 --output data/融资融券近五年合并分析.xlsx
python valuation/fetch.py --config valuation/indexes.json --output data/valuation.json
python buffett/fetch.py --years 10 --output data/buffett.json --csv data/buffett_indicator_data.csv
python build_site.py --input data/融资融券近五年合并分析.xlsx --output docs/margin.html
python valuation/build.py --input data/valuation.json --output docs/valuation.html
python buffett/build.py --input data/buffett.json --output docs/buffett.html
python build_portal.py --input portal_template.html --output docs/index.html
python -m unittest discover -s tests -v
```

本地这些命令不会自动执行工作流的模块间隔；定时/手动 Actions 中的顺序间隔由 `.github/workflows/update.yml` 实施。`run.log` 与 `data/` 不应提交仓库；`docs/` 中的预览包含本地实测数据，首次成功运行后由 Pages 构建产物替换。

## 项目结构

- `portal_template.html`, `build_portal.py`：首页及链接完整性校验。
- `site_template.html`, `build_site.py`, `eastmoney_margin_5y_mergechatgpt.py`：两融数据与图表，包含先前的缺失百分位修复。
- `valuation/indexes.json`, `valuation/fetch.py`, `valuation/template.html`, `valuation/build.py`：白名单指数估值。
- `buffett/buffett_indicator_china_original.py`, `buffett/fetch.py`, `buffett/template.html`, `buffett/build.py`：原稿备份、低频抓取、百分位计算和看板。
- `.github/workflows/update.yml`, `requirements.txt`, `tests/`：自动更新、依赖和离线测试。
