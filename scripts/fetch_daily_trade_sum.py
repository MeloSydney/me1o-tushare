#!/usr/bin/env python3
"""Fetch and validate the latest N Shanghai/Shenzhen A-share trading days."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
from pathlib import Path
import sys
import time
import urllib.error
import urllib.request

API_URL = "http://api.tushare.pro"
TUSHARE_DAILY_ROW_LIMIT = 6000
DEFAULT_ENV_FILE = Path("/Users/melo/doc-Dgf/Tushare/.env")
DEFAULT_OUTPUT_ROOT = Path("/Users/melo/doc-Dgf/Tushare")
FIELDS = [
    "trade_date",
    "shanghai_amount_100m_cny",
    "shenzhen_amount_100m_cny",
    "total_amount_100m_cny",
    "shanghai_stock_count",
    "shenzhen_stock_count",
]


def load_token(path: Path) -> str:
    token = os.getenv("TUSHARE_TOKEN") or os.getenv("TS_TOKEN")
    if token:
        return token.strip()
    if not path.exists():
        raise RuntimeError(f"找不到 Tushare Token 文件：{path}")
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            return line.strip("\"'")
        key, value = line.split("=", 1)
        if key.strip() in {"TUSHARE_TOKEN", "TS_TOKEN", "TOKEN"}:
            return value.strip().strip("\"'")
    raise RuntimeError(f"无法从 {path} 读取 Tushare Token")


def api_call(token: str, trade_date: str) -> list[list]:
    payload = {
        "api_name": "daily",
        "token": token,
        "params": {"trade_date": trade_date},
        "fields": "ts_code,trade_date,amount",
    }
    req = urllib.request.Request(
        API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            result = json.load(response)
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError(f"Tushare 网络请求失败：{exc}") from exc
    if result.get("code") != 0:
        raise RuntimeError(
            f"Tushare API 错误 {result.get('code')}：{result.get('msg', '未知错误')}"
        )
    items = (result.get("data") or {}).get("items") or []
    if len(items) >= TUSHARE_DAILY_ROW_LIMIT:
        raise RuntimeError(
            f"{trade_date} 返回 {len(items)} 条，达到 Tushare daily 单次上限 "
            f"{TUSHARE_DAILY_ROW_LIMIT}，可能被截断，拒绝生成不完整汇总"
        )
    return items


def summarize(rows: list[list], requested_date: str) -> dict | None:
    if not rows:
        return None
    sh_amount = sz_amount = 0.0
    sh_count = sz_count = 0
    returned_dates = set()
    for ts_code, trade_date, amount in rows:
        returned_dates.add(str(trade_date))
        value = float(amount or 0)
        if str(ts_code).endswith(".SH"):
            sh_amount += value
            sh_count += 1
        elif str(ts_code).endswith(".SZ"):
            sz_amount += value
            sz_count += 1
    if returned_dates != {requested_date}:
        raise RuntimeError(
            f"日期 {requested_date} 的响应包含异常日期：{sorted(returned_dates)}"
        )
    # Tushare daily.amount 的单位是千元；除以 100,000 转为亿元。
    sh = round(sh_amount / 100_000, 2)
    sz = round(sz_amount / 100_000, 2)
    return {
        "trade_date": dt.datetime.strptime(requested_date, "%Y%m%d").strftime("%Y-%m-%d"),
        "shanghai_amount_100m_cny": sh,
        "shenzhen_amount_100m_cny": sz,
        "total_amount_100m_cny": round(sh + sz, 2),
        "shanghai_stock_count": sh_count,
        "shenzhen_stock_count": sz_count,
    }


def validate_records(
    records: list[dict], end: dt.date, expected_count: int
) -> list[str]:
    errors: list[str] = []
    dates = [dt.date.fromisoformat(row["trade_date"]) for row in records]
    if not records:
        errors.append("输出无交易日记录")
    if len(records) != expected_count:
        errors.append(f"有效交易日数量不足：期望 {expected_count}，实际 {len(records)}")
    if dates != sorted(dates):
        errors.append("交易日期未按升序排列")
    if len(dates) != len(set(dates)):
        errors.append("存在重复交易日期")
    for row, day in zip(records, dates):
        if day > end:
            errors.append(f"{day} 晚于截止日期 {end}")
        if day.weekday() >= 5:
            errors.append(f"{day} 为周末却出现在结果中")
        sh = float(row["shanghai_amount_100m_cny"])
        sz = float(row["shenzhen_amount_100m_cny"])
        total = float(row["total_amount_100m_cny"])
        if sh <= 0 or sz <= 0:
            errors.append(f"{day} 沪市或深市成交额非正数")
        if abs(round(sh + sz, 2) - total) > 0.001:
            errors.append(f"{day} 合计成交额与沪深分项不一致")
        if int(row["shanghai_stock_count"]) <= 0 or int(row["shenzhen_stock_count"]) <= 0:
            errors.append(f"{day} 股票数量异常")
    return errors


def write_csv(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(records)


def read_csv(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="获取截至指定日期最近 N 个有效交易日的沪深 A 股成交额"
    )
    parser.add_argument("--days", type=int, default=30, help="有效交易日数量，默认 30")
    parser.add_argument(
        "--end-date",
        help="统计截止日期 YYYY-MM-DD，默认今天",
    )
    parser.add_argument(
        "--max-lookback-days",
        type=int,
        default=180,
        help="最多向前扫描的自然日数，默认 180",
    )
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="输出目录；默认 /Users/melo/doc-Dgf/Tushare/MMDD",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.days < 1:
        raise RuntimeError("--days 必须大于 0")
    if args.max_lookback_days < args.days:
        raise RuntimeError("--max-lookback-days 不能小于 --days")
    try:
        end = dt.date.fromisoformat(args.end_date) if args.end_date else dt.date.today()
    except ValueError as exc:
        raise RuntimeError("--end-date 格式必须为 YYYY-MM-DD") from exc
    token = load_token(args.env_file.expanduser())
    output_dir = (
        args.output_dir.expanduser()
        if args.output_dir
        else DEFAULT_OUTPUT_ROOT / end.strftime("%m%d")
    )

    # 从截止日倒序扫描，直到拿满 N 个真实有行情的交易日。这样 --days 表示
    # “有效记录数”，而不是会因周末和节假日缩水的自然日窗口。
    records: list[dict] = []
    no_data_dates: list[str] = []
    weekends: list[dt.date] = []
    scanned_dates: list[dt.date] = []
    for offset in range(args.max_lookback_days):
        if len(records) >= args.days:
            break
        day = end - dt.timedelta(days=offset)
        scanned_dates.append(day)
        if day.weekday() >= 5:
            weekends.append(day)
            continue
        key = day.strftime("%Y%m%d")
        row = summarize(api_call(token, key), key)
        progress = f"{len(records)}/{args.days}"
        if row is None:
            no_data_dates.append(day.isoformat())
            print(f"[{progress}] {day} 无数据，按休市日剔除", flush=True)
        else:
            records.append(row)
            print(f"[{len(records)}/{args.days}] {day} 获取成功", flush=True)
        time.sleep(0.12)

    records.sort(key=lambda item: item["trade_date"])
    scan_start = min(scanned_dates) if scanned_dates else end
    csv_path = output_dir / "daily_trade_sum.csv"
    validation_path = output_dir / "daily_trade_sum_validation.json"
    write_csv(csv_path, records)

    # Re-read the actual artifact, then independently request the latest included day.
    persisted = read_csv(csv_path)
    errors = validate_records(persisted, end, args.days)
    latest_recheck = None
    if persisted:
        latest = persisted[-1]
        latest_key = latest["trade_date"].replace("-", "")
        latest_recheck = summarize(api_call(token, latest_key), latest_key)
        for field in FIELDS:
            left = str(latest[field])
            right = str(latest_recheck[field]) if latest_recheck else ""
            if field.endswith("_100m_cny"):
                if abs(float(left) - float(right)) > 0.001:
                    errors.append(f"最新日复查字段不一致：{field} ({left} != {right})")
            elif left != right:
                errors.append(f"最新日复查字段不一致：{field} ({left} != {right})")

    validation = {
        "status": "passed" if not errors else "failed",
        "source": "Tushare daily API",
        "scope": "Shanghai and Shenzhen A-share stock turnover; excludes ETFs, bonds and Beijing exchange",
        "unit": "100 million CNY",
        "window": {
            "requested_trading_days": args.days,
            "scanned_calendar_days": len(scanned_dates),
            "scan_start_date": scan_start.isoformat(),
            "end_date": end.isoformat(),
            "first_output_trade_date": persisted[0]["trade_date"] if persisted else None,
            "last_output_trade_date": persisted[-1]["trade_date"] if persisted else None,
        },
        "counts": {
            "requested_trading_days": args.days,
            "scanned_calendar_days": len(scanned_dates),
            "weekend_days_excluded": len(weekends),
            "weekday_no_data_days_excluded": len(no_data_dates),
            "trading_days_output": len(persisted),
        },
        "weekends_excluded": [day.isoformat() for day in weekends],
        "weekday_no_data_dates_excluded": no_data_dates,
        "latest_record_rechecked": latest_recheck,
        "checks": {
            "csv_reloaded": True,
            "dates_unique_and_sorted": not any("重复" in e or "升序" in e for e in errors),
            "dates_not_after_end": not any("晚于截止日期" in e for e in errors),
            "requested_trading_day_count_met": not any("有效交易日数量不足" in e for e in errors),
            "weekends_absent": not any("周末" in e for e in errors),
            "amounts_positive_and_totals_match": not any(
                "成交额" in e or "合计" in e for e in errors
            ),
            "latest_day_api_recheck": not any("复查" in e for e in errors),
        },
        "errors": errors,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    validation_path.write_text(
        json.dumps(validation, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"CSV：{csv_path}")
    print(f"验证报告：{validation_path}")
    print(
        f"扫描 {scan_start} 至 {end}：输出 {len(persisted)}/{args.days} 个有效交易日，"
        f"剔除周末 {len(weekends)} 天、工作日无行情 {len(no_data_dates)} 天"
    )
    if persisted:
        latest = persisted[-1]
        print(
            f"最新 {latest['trade_date']}：沪市 {float(latest['shanghai_amount_100m_cny']):.2f} 亿元，"
            f"深市 {float(latest['shenzhen_amount_100m_cny']):.2f} 亿元，"
            f"合计 {float(latest['total_amount_100m_cny']):.2f} 亿元"
        )
    print(f"验证：{validation['status']}")
    if errors:
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        raise SystemExit(1)
