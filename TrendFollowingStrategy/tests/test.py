import json
import math
import time
import random

from curl_cffi import requests          # 关键替换：用 curl_cffi 的 requests
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib

# 中文字体设置
matplotlib.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'Arial Unicode MS']
matplotlib.rcParams['axes.unicode_minus'] = False

# ==================== 配置 ====================
PUSH2_URL = "https://push2.eastmoney.com/api/qt/clist/get"

_FS_MAP = {
    "industry": "m:90 t:2",   # 行业板块
    "concept":  "m:90 t:3",   # 概念板块
}

_FIELDS = "f12,f14,f3,f62,f184,f66,f72,f78,f84"

_HEADERS = {
    "Accept": "*/*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": "https://data.eastmoney.com/",
    "Cookie": (
        "qgqp_b_id=9ea9db0075cd81fa8f5a4da22dc04d6d; "
        "st_nvi=-MjHz4hSNcqscYgNWkZmKaece; "
        "nid18=08aa3aed4856854b19f0367f27bce932; "
        "nid18_create_time=1780752336315; "
        "gviem=zhF8uiNt8jiTruRCf7hoM33ed; "
        "gviem_create_time=1780752336315; "
        "websitepoptg_api_time=1781102353820; "
        "st_si=83912047470544; "
        "st_asi=delete; "
        "fullscreengg=1; "
        "fullscreengg2=1; "
        "wsc_checkuser_ok=1; "
        "st_pvi=96578045484995; "
        "st_sp=2026-06-06%2021%3A25%3A36; "
        "st_inirUrl=https%3A%2F%2Fcn.bing.com%2F; "
        "st_sn=10; "
        "st_psi=20260610224401390-113200301321-9127613940"
    ),
}


_PAGE_SIZE = 100
_INTER_PAGE_SLEEP = 1.5
_MAX_RETRIES = 3

# ==================== 代理配置（可选） ====================
# 如果 IP 已被限流，填入你的代理地址；留空则不使用代理
PROXY_URL = ""   # 示例: "http://user:pass@127.0.0.1:7890"


def _build_session() -> requests.Session:
    """
    创建带 Chrome TLS 指纹伪装的 Session。
    impersonate="chrome124" 是关键，让底层 libcurl 重放 Chrome 的 TLS/HTTP2 指纹。
    """
    kwargs = {"impersonate": "chrome124"}
    if PROXY_URL:
        kwargs["proxies"] = {"http": PROXY_URL, "https": PROXY_URL}

    session = requests.Session(**kwargs)
    session.headers.update(_HEADERS)
    return session


def _request_page(session: requests.Session, sector_type: str,
                  page: int, timeout: float = 15.0) -> dict:
    """请求单页，带重试与指数退避。"""
    if sector_type not in _FS_MAP:
        raise ValueError(f"sector_type 必须是 {list(_FS_MAP.keys())} 之一")

    params = {
        "pn": str(page),
        "pz": str(_PAGE_SIZE),
        "po": "1",
        "np": "1",
        "ut": "b2884a393a59ad64002292a3e90d46a5",
        "fltt": "2",
        "invt": "2",
        "fid": "f62",               # 按主力净流入排序
        "fs": _FS_MAP[sector_type],
        "fields": _FIELDS,
        "_": int(time.time() * 1000),
    }

    last_err = None
    for attempt in range(_MAX_RETRIES):
        try:
            if attempt > 0:
                time.sleep(1.5 ** attempt)  # 指数退避：1.5s, 2.25s, 3.375s

            r = session.get(PUSH2_URL, params=params, timeout=timeout)
            r.raise_for_status()

            # 清洗 JSONP 前缀（如 jQuery1123(...)）
            text = r.text
            if text.startswith("jQuery") or text.startswith("("):
                start = text.index("(") + 1
                end = text.rindex(")")
                text = text[start:end]

            return json.loads(text)

        except Exception as e:
            last_err = e
            print(f"  第 {attempt+1}/{_MAX_RETRIES} 次请求失败: {e}")

    raise RuntimeError(f"page={page} 重试 {_MAX_RETRIES} 次后仍失败: {last_err}")


def _to_float(val):
    if val in (None, "-", ""):
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def fetch_sector_fund_flow(sector_type: str = "industry") -> pd.DataFrame:
    """
    获取板块资金流全量快照。
    使用 curl_cffi Session 模拟 Chrome 指纹，绕过 TLS 检测。
    """
    session = _build_session()

    try:
        # 第一页：获取总数，必须成功
        first = _request_page(session, sector_type, page=1)
        data = first.get("data") or {}
        total = data.get("total") or 0
        pages = max(1, math.ceil(total / _PAGE_SIZE))

        diff = data.get("diff") or []
        if isinstance(diff, dict):
            diff = list(diff.values())
        all_rows = list(diff)

        # 后续页：尽力而为，失败则跳过
        for page in range(2, pages + 1):
            # 随机抖动，模拟真人操作节奏
            time.sleep(_INTER_PAGE_SLEEP + random.uniform(0, 1.0))
            try:
                j = _request_page(session, sector_type, page=page)
            except RuntimeError as e:
                print(f"  跳过 page {page}: {e}")
                continue

            d = (j.get("data") or {}).get("diff") or []
            if isinstance(d, dict):
                d = list(d.values())
            all_rows.extend(d)

    finally:
        session.close()

    # 去重 + 字段整理
    seen = set()
    records = []
    for row in all_rows:
        code = row.get("f12")
        name = row.get("f14")
        if not code or not name or code in seen:
            continue
        seen.add(code)
        records.append({
            "code":            code,
            "name":            name,
            "pct_chg":         _to_float(row.get("f3")),
            "main_net":        _to_float(row.get("f62")),
            "main_net_rate":   _to_float(row.get("f184")),
            "super_net":       _to_float(row.get("f66")),
            "big_net":         _to_float(row.get("f72")),
            "mid_net":         _to_float(row.get("f78")),
            "small_net":       _to_float(row.get("f84")),
        })

    df = pd.DataFrame(records)

    # 单位换算：元 → 亿元
    for col in ["main_net", "super_net", "big_net", "mid_net", "small_net"]:
        if col in df.columns:
            df[col] = df[col] / 1e8

    df = df.rename(columns={
        "main_net":      "主力净流入(亿)",
        "main_net_rate": "主力净占比(%)",
        "super_net":     "超大单净流入(亿)",
        "big_net":       "大单净流入(亿)",
        "mid_net":       "中单净流入(亿)",
        "small_net":     "小单净流入(亿)",
    })
    return df


# ==================== 绘图 ====================
def plot_sector_fund_flow(df: pd.DataFrame,
                          sector_label: str = "行业板块",
                          top_n: int = 15):
    df_sorted = df.sort_values("主力净流入(亿)", ascending=False).head(top_n)

    fig, ax = plt.subplots(figsize=(12, 7))
    colors = ["#d62728" if v >= 0 else "#2ca02c" for v in df_sorted["主力净流入(亿)"]]
    bars = ax.barh(df_sorted["name"], df_sorted["主力净流入(亿)"], color=colors)

    for bar, val in zip(bars, df_sorted["主力净流入(亿)"]):
        offset = abs(val) * 0.02 if val >= 0 else -abs(val) * 0.08
        ax.text(bar.get_width() + offset,
                bar.get_y() + bar.get_height() / 2,
                f"{val:.2f}亿",
                va="center",
                ha="left" if val >= 0 else "right",
                fontsize=9)

    ax.axvline(x=0, color="gray", linestyle="--", linewidth=0.8)
    ax.invert_yaxis()
    ax.set_xlabel("主力净流入（亿元）", fontsize=12)
    ax.set_title(f"{sector_label} — 主力净流入排名（前 {top_n}）", fontsize=14, pad=15)
    plt.tight_layout()
    plt.show()


# ==================== 主程序 ====================
if __name__ == "__main__":
    print("正在获取行业板块资金流数据（curl_cffi + Chrome 指纹）...")
    df = fetch_sector_fund_flow(sector_type="industry")
    print(f"共获取 {len(df)} 个板块\n")

    print(df.head(10)[["name", "主力净流入(亿)", "主力净占比(%)", "pct_chg"]].to_string(index=False))

    plot_sector_fund_flow(df, sector_label="行业板块", top_n=15)