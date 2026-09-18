import json
import time
from curl_cffi import requests
import pandas as pd

# ==================== 配置 ====================
PUSH2HIS_URL = "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get"

# 沿用你已验证有效的 Cookie
COOKIE_STR = "qgqp_b_id=...; st_si=...; ..."

_HEADERS = {
    "Accept": "*/*",
    "Referer": "https://data.eastmoney.com/",
    "Cookie": COOKIE_STR,
}

def fetch_sector_fund_flow_history(
    secid: str,
    beg: str = "20250101",
    end: str = "20250917",
    klt: int = 101,
) -> pd.DataFrame:
    """
    获取指定板块的历史资金流数据。
    :param secid: 板块市场代码，格式如 "90.BK0438"
    :param beg: 开始日期 YYYYMMDD
    :param end: 结束日期 YYYYMMDD
    :param klt: K线类型，101=日线
    """
    params = {
        "secid": secid,
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "klt": str(klt),
        "fqt": "1",
        "beg": beg,
        "end": end,
        "lmt": "1000",          # 最多返回条数
        "_": int(time.time() * 1000),
    }

    with requests.Session(impersonate="chrome124") as session:
        session.headers.update(_HEADERS)
        r = session.get(PUSH2HIS_URL, params=params, timeout=15)
        r.raise_for_status()

    # 清理 JSONP 前缀
    text = r.text
    if text.startswith("jQuery") or text.startswith("("):
        start = text.index("(") + 1
        end_idx = text.rindex(")")
        text = text[start:end_idx]

    data = json.loads(text)
    klines = (data.get("data") or {}).get("klines") or []

    # 解析每条 kline："日期,主力净额,小单净额,..."
    records = []
    for line in klines:
        parts = line.split(",")
        if len(parts) < 11:
            continue
        records.append({
            "date":            parts[0],
            "main_net":        float(parts[1]) / 1e8,    # 亿
            "small_net":       float(parts[2]) / 1e8,
            "mid_net":         float(parts[3]) / 1e8,
            "big_net":         float(parts[4]) / 1e8,
            "super_net":       float(parts[5]) / 1e8,
            "main_net_rate":   float(parts[6]),           # %
            "small_net_rate":  float(parts[7]),
            "mid_net_rate":    float(parts[8]),
            "big_net_rate":    float(parts[9]),
            "super_net_rate":  float(parts[10]),
        })

    df = pd.DataFrame(records)
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)

    return df

# ==================== 使用示例 ====================
if __name__ == "__main__":
    # 汽车服务板块（BK0438）近30个交易日的历史资金流
    df = fetch_sector_fund_flow_history(
        secid="90.BK0438",
        beg="20250801",
        end="20250917",
    )
    print(df.tail(10).to_string(index=False))