# 两融观察｜东方财富近五年数据看板

自动抓取东方财富公开融资融券数据，生成三工作表 Excel，并将趋势图和历史百分位发布到 GitHub Pages。页面采用黑白编辑式排版、色块分区和响应式图表。**这是项目模板；页面需要首次运行成功后才有真实数据。**

## 页面内容

- 最新可用交易日：融资余额、沪深300、融资买入额、买入强度和两个历史百分位；每张卡片标注该指标自身的日期。
- 近 1 / 3 / 5 年切换：融资及两融余额与沪深300、融资买入额与买入强度、平均维持担保比例。
- 三项近五年百分位：融资买入额占融资余额比例、参与交易投资者占有负债投资者比例、平均维持担保比例。百分位始终按整段五年有效样本计算。
- 数据说明和原始网页入口；页面非投资建议。

## 一次性部署到 GitHub

1. 在 GitHub 新建**公开仓库**，将本目录内所有文件和 `.github/workflows/update.yml` 一起上传到仓库根目录。不要上传账号密码或 `run.log`。
2. 仓库 **Settings → Pages → Build and deployment → Source** 选择 **GitHub Actions**。仓库设置中的 Actions 权限须允许工作流运行、Pages 部署。公开仓库 Pages 一般无需额外费用；私人仓库支持情况以账户方案为准。
3. 打开 **Actions → 更新两融数据与图表 → Run workflow** 手动运行一次。成功后在该次任务的 `deploy` 步骤及 Settings → Pages 查看网址，通常为 `https://<用户名>.github.io/<仓库名>/`。
4. 此后工作流按 UTC 周一至周五 11:30（北京时间 19:30）计划运行；GitHub 定时调度可能延迟或因仓库长期不活跃而停用。节假日或收盘后数据未更新时页面可能沿用最近交易日，请以页面日期为准。
5. 每次运行的 Excel 与 `run.log` 在 Actions 运行记录下方 **Artifacts** 下载，默认保留 90 天。工作流不把数据和日志提交到 Git 仓库。只有抓取、生成及测试都成功后才部署新页面，失败时 Pages 保留上一次成功部署的内容。

> **重要**：GitHub 的 README.md 不会自动显示交互图表。交互图表在 GitHub Pages 网页中；README 提供使用说明。网页图表通过 ECharts CDN 加载，访问图表需要网络连通 CDN。

## 本地运行

```bash
python -m pip install -r requirements.txt
python eastmoney_margin_5y_mergechatgpt.py --years 5 --output data/融资融券近五年合并分析.xlsx
python build_site.py --input data/融资融券近五年合并分析.xlsx --output docs/index.html
python -m unittest discover -s tests -v
```

打开 `docs/index.html` 查看页面。原始脚本依旧支持 `--end-date YYYY-MM-DD`、`--years` 和 `--output`。本地生成页面前请先有有效 Excel。构建器把图表数据嵌入 HTML，页面无需后端；但 ECharts 脚本仍需联网。若本地抓取失败，检查东方财富页面及接口变化、网络可达性和 `run.log`；勿把失败时的空页面当作已更新数据。

## 文件结构

- `eastmoney_margin_5y_mergechatgpt.py`：用户提供的原始抓取、合并、计算与 Excel 导出程序，保持原样。
- `build_site.py`：读取 Excel、校验必要列并注入网页数据；写入 `run.log`。
- `site_template.html`：响应式页面模板与 ECharts 图表。
- `.github/workflows/update.yml`：定时或手动执行、上传 Excel/日志、部署 Pages。
- `tests/`：计算逻辑和网页构建的离线测试。
- `docs/index.html`：首次成功运行后生成，作为 Pages 部署目录。

## 口径与注意事项

- 原程序按交易日期对两个数据源做一对一外连接；缺值不连接线，最近交易日可能不齐。比例单位为**百分点**，不是 Excel 百分比单元格式。
- 平均秩百分位采用 `rank(method="average", pct=True) × 100`；不同回溯窗口或后续新数据会改变历史百分位。
- 东方财富接口并非本项目维护，若接口、字段、限流政策变化，自动更新可能失败。当前项目尚未在 GitHub Actions 环境实跑或验证真实数据可得性；首次部署后以 Actions 运行结果为准。
- 仅用于数据观察、教学研究，不构成投资建议。
