---
name: daily-trade-sum
description: 获取截至指定日期最近 30 个有效交易日的沪深两市每日 A 股成交额，自动跳过周末、节假日及无行情日期，使用 Tushare 数据源，输出 CSV 和机器可读验证报告。当用户提到 dailyTradeSum、沪深每日成交额、近30天成交额、沪市深市成交统计时使用。
compatibility: Requires Python 3, network access to api.tushare.pro, and a Tushare token in /Users/melo/doc-Dgf/Tushare/.env.
---

# dailyTradeSum

获取截至指定日期最近 30 个**有效交易日**的沪深每日 A 股成交额。必须执行脚本完成数据抓取和验证，不要凭记忆生成数据。

## 数据口径

- 数据源：Tushare `daily` 接口。
- 时间范围：默认以今天为截止日，向前扫描并收集满 30 个**有日行情数据的交易日**，不是 30 个自然日。
- 休市处理：周末直接跳过；工作日逐日请求，接口无日行情时按节假日、休市日或尚未出数日期排除。脚本默认最多向前扫描 180 个自然日。
- 沪市：`ts_code` 以 `.SH` 结尾的股票成交额之和。
- 深市：`ts_code` 以 `.SZ` 结尾的股票成交额之和。
- 单位：亿元。Tushare `daily.amount` 原始单位为千元，脚本除以 `100000` 转换为亿元。
- 范围：A 股股票，不包含 ETF、债券和北交所。
- Tushare 限制防护：`daily` 官方单次上限为 6000 条；若某日响应达到该上限，脚本视为可能截断并直接失败，不生成可能不完整的汇总。逐日调用并保持约 0.12 秒间隔，以适配每分钟 500 次的基础频率上限。

## 凭据

默认从 `/Users/melo/doc-Dgf/Tushare/.env` 读取 Token，同时兼容：

1. 文件内直接放置裸 Token；
2. `TUSHARE_TOKEN=...`、`TS_TOKEN=...` 或 `TOKEN=...`；
3. 环境变量 `TUSHARE_TOKEN` 或 `TS_TOKEN`。

不得在终端输出或报告中泄露 Token。

## 执行

从本文件所在 skill 目录执行：

```bash
python3 scripts/fetch_daily_trade_sum.py
```

可选参数：

```bash
python3 scripts/fetch_daily_trade_sum.py \
  --days 30 \
  --max-lookback-days 180 \
  --end-date YYYY-MM-DD \
  --env-file /Users/melo/doc-Dgf/Tushare/.env \
  --output-dir /path/to/output
```

默认输出目录为 `/Users/melo/doc-Dgf/Tushare/MMDD/`，其中 `MMDD` 是截止日期的月日。

## 输出

- `daily_trade_sum.csv`：逐交易日成交额，包含日期、沪市成交额、深市成交额、两市合计及参与汇总的股票数量。
- `daily_trade_sum_validation.json`：扫描日期窗口、目标/实际有效交易日数、剔除日期、最新交易日 API 二次复查及错误列表。

## 强制验证

每次运行必须确认脚本退出码为 0，并检查验证报告中的：

- `status` 必须为 `passed`；
- CSV 已重新读取；
- 日期唯一且升序；
- 输出记录数必须等于 `--days`（默认 30 个有效交易日）；
- 日期不得晚于截止日期；
- 周末没有出现在 CSV；
- 沪深成交额均为正数，且合计等于两市分项之和；
- 最新交易日重新请求 Tushare 后与 CSV 完全一致；
- `weekday_no_data_dates_excluded` 中列出国庆等工作日休市日期。

若验证失败，必须明确报告失败项，不得将结果描述为成功。

## 最终报告

向用户简洁报告：

1. 扫描起止日期、首末有效交易日与实际交易日数量；
2. 剔除的周末天数和工作日休市天数；
3. 最新交易日沪市、深市及合计成交额；
4. CSV 与验证报告的绝对路径；
5. 验证状态及口径说明。
