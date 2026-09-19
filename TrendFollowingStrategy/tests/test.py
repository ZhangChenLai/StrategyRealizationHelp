import json
import time
from curl_cffi import requests
import pandas as pd

import numpy as np
import matplotlib.pyplot as plt
import matplotlib
from matplotlib import font_manager

# ==================== 配置 ====================
PUSH2HIS_URL = "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get"

# 沿用你已验证有效的 Cookie
COOKIE_STR = "qgqp_b_id=...; st_si=...; ..."

_HEADERS = {
    "Accept": "*/*",
    "Referer": "https://data.eastmoney.com/",
    "Cookie": COOKIE_STR,
}
def fetch_sector_code_map(sector_type: str = "industry") -> dict:
    """获取 {板块名称: secid} 的映射字典。"""
    fs_map = {"industry": "m:90 t:2", "concept": "m:90 t:3"}
    params = {
        "pn": "1", "pz": "500",
        "po": "1", "np": "1",
        "ut": "b2884a393a59ad64002292a3e90d46a5",
        "fltt": "2", "invt": "2",
        "fid": "f62",
        "fs": fs_map[sector_type],
        "fields": "f12,f14",      # f12=板块代码, f14=板块名称
        "_": int(time.time() * 1000),
    }
    with requests.Session(impersonate="chrome124") as session:
        session.headers.update(_HEADERS)
        r = session.get("https://push2.eastmoney.com/api/qt/clist/get",
                        params=params, timeout=15)
    text = r.text
    if text.startswith("jQuery") or text.startswith("("):
        text = text[text.index("(") + 1: text.rindex(")")]
    data = json.loads(text)
    diff = (data.get("data") or {}).get("diff") or []
    return {row["f14"]: f"90.{row['f12']}" for row in diff}

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

def fetch_all_sectors_history(
    sector_type: str = "industry",
    beg: str = "20250801",
    end: str = "20250917",
    inter_sleep: float = 2.0,
):
    """获取所有板块的历史资金流，合并为一张长表。"""
    code_map = fetch_sector_code_map(sector_type)
    print(f"共 {len(code_map)} 个板块，开始逐一下载...")

    all_dfs = []
    for i, (name, secid) in enumerate(code_map.items(), 1):
        try:
            df = fetch_sector_fund_flow_history(secid, beg=beg, end=end)
            if not df.empty:
                df.insert(0, "sector_name", name)
                df.insert(1, "secid", secid)
                all_dfs.append(df)
            print(f"  [{i}/{len(code_map)}] {name} — {len(df)} 条")
        except Exception as e:
            print(f"  [{i}/{len(code_map)}] {name} 失败: {e}")
        time.sleep(inter_sleep)   # 东财 push2his 约 20-25 reqs/IP 限流

    if all_dfs:
        return pd.concat(all_dfs, ignore_index=True)
    return pd.DataFrame()



matplotlib.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'Arial Unicode MS']
matplotlib.rcParams['axes.unicode_minus'] = False
matplotlib.rcParams['figure.dpi'] = 110


# ============================================================
# 图 1：单板块资金流时间序列（主力净流入柱 + 累计净流入线）
# ============================================================
def plot_single_sector_flow(df: pd.DataFrame, sector_name: str = "板块"):
    """
    df 需包含列：date, main_net（亿元）, main_net_rate（%）
    """
    d = df.sort_values("date").reset_index(drop=True).copy()
    d["cum_main_net"] = d["main_net"].cumsum()   # 累计净流入

    fig, ax1 = plt.subplots(figsize=(14, 6))

    # 左轴：每日主力净流入柱状图（红正绿负）
    colors = ["#d62728" if v >= 0 else "#2ca02c" for v in d["main_net"]]
    bars = ax1.bar(d["date"], d["main_net"], color=colors, alpha=0.75,
                   width=0.7, label="每日主力净流入")
    ax1.axhline(0, color="gray", linewidth=0.8, linestyle="--")
    ax1.set_ylabel("每日主力净流入（亿元）", fontsize=11, color="#333")
    ax1.tick_params(axis="y", labelcolor="#333")

    # 右轴：累计净流入折线
    ax2 = ax1.twinx()
    ax2.plot(d["date"], d["cum_main_net"], color="#1f77b4",
             linewidth=2.0, marker="o", markersize=3.5, label="累计主力净流入")
    ax2.set_ylabel("累计主力净流入（亿元）", fontsize=11, color="#1f77b4")
    ax2.tick_params(axis="y", labelcolor="#1f77b4")

    # 合并图例
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc="upper left", fontsize=10)

    ax1.set_title(f"{sector_name} — 每日主力净流入与累计趋势",
                  fontsize=14, pad=15)
    ax1.set_xlabel("日期", fontsize=11)
    fig.autofmt_xdate(rotation=45)
    plt.tight_layout()
    plt.show()


# ============================================================
# 图 2：多板块资金流对比（累计净流入折线）
# ============================================================
def plot_multi_sector_flow(df_all: pd.DataFrame,
                           sectors: list,
                           value_col: str = "main_net"):
    """
    df_all 需包含：date, sector_name, main_net
    sectors: 要对比的板块名称列表
    """
    fig, ax = plt.subplots(figsize=(14, 6))

    for name in sectors:
        sub = df_all[df_all["sector_name"] == name].sort_values("date")
        if sub.empty:
            print(f"⚠️ 未找到板块: {name}")
            continue
        cum = sub[value_col].cumsum()
        ax.plot(sub["date"], cum, linewidth=2.0, marker="o",
                markersize=3, label=name)

    ax.axhline(0, color="gray", linewidth=0.8, linestyle="--")
    ax.set_ylabel("累计主力净流入（亿元）", fontsize=11)
    ax.set_xlabel("日期", fontsize=11)
    ax.set_title("多板块累计主力净流入对比", fontsize=14, pad=15)
    ax.legend(loc="best", fontsize=10, ncol=2)
    fig.autofmt_xdate(rotation=45)
    plt.tight_layout()
    plt.show()


# ============================================================
# 图 3：板块资金流热力图（板块 × 日期）
# ============================================================
def plot_sector_heatmap(df_all: pd.DataFrame,
                        top_n: int = 20,
                        value_col: str = "main_net",
                        date_range: tuple = None):
    """
    行列：板块 × 日期，颜色深浅表示净流入强度。
    - 板块按区间内累计净流入排序，取前 top_n 个
    - date_range: (起, 止) 可选，如 ("2025-08-01", "2025-09-17")
    """
    d = df_all.copy()
    d["date"] = pd.to_datetime(d["date"])

    if date_range:
        d = d[(d["date"] >= pd.to_datetime(date_range[0])) &
              (d["date"] <= pd.to_datetime(date_range[1]))]

    # 按累计净流入挑出最强的 top_n 个板块
    rank = (d.groupby("sector_name")[value_col]
              .sum()
              .sort_values(ascending=False)
              .head(top_n)
              .index.tolist())
    d = d[d["sector_name"].isin(rank)]

    # 透视成 板块 × 日期 矩阵
    pivot = d.pivot_table(index="sector_name", columns="date",
                          values=value_col, aggfunc="sum")
    pivot = pivot.reindex(rank)   # 保持累计排序

    fig, ax = plt.subplots(figsize=(15, max(6, top_n * 0.4)))

    # 对称色标，让 0 居中，红色正、绿色负
    vmax = np.nanmax(np.abs(pivot.values))
    im = ax.imshow(pivot.values, aspect="auto", cmap="RdYlGn_r",
                   vmin=-vmax, vmax=vmax)

    ax.set_xticks(range(len(pivot.columns)))
    ax.set_xticklabels([c.strftime("%m-%d") for c in pivot.columns],
                       rotation=45, ha="right", fontsize=9)
    ax.set_yticks(range(len(pivot.index)))
    ax.set_yticklabels(pivot.index, fontsize=9)

    cbar = plt.colorbar(im, ax=ax, fraction=0.025, pad=0.02)
    cbar.set_label("主力净流入（亿元）", fontsize=10)

    ax.set_title(f"板块资金流热力图（Top {top_n} 板块）", fontsize=14, pad=15)
    ax.set_xlabel("日期", fontsize=11)
    ax.set_ylabel("板块", fontsize=11)
    plt.tight_layout()
    plt.show()


# ============================================================
# 图 4（可选）：单板块资金结构堆叠图
# ============================================================
def plot_fund_structure(df: pd.DataFrame, sector_name: str = "板块"):
    """
    展示超大单/大单/中单/小单 四类资金的每日净流入堆叠结构。
    df 需包含：date, super_net, big_net, mid_net, small_net
    """
    d = df.sort_values("date").reset_index(drop=True).copy()

    fig, ax = plt.subplots(figsize=(14, 6))
    x = np.arange(len(d))

    ax.bar(x, d["super_net"], color="#c0392b", label="超大单", width=0.7)
    ax.bar(x, d["big_net"], bottom=d["super_net"], color="#e67e22",
           label="大单", width=0.7)
    ax.bar(x, d["mid_net"],
           bottom=d["super_net"] + d["big_net"],
           color="#95a5a6", label="中单", width=0.7)
    ax.bar(x, d["small_net"],
           bottom=d["super_net"] + d["big_net"] + d["mid_net"],
           color="#27ae60", label="小单", width=0.7)

    ax.axhline(0, color="black", linewidth=0.8, linestyle="--")
    ax.set_xticks(x[::max(1, len(x)//15)])
    ax.set_xticklabels([d["date"].iloc[i].strftime("%m-%d")
                        for i in range(0, len(x), max(1, len(x)//15))],
                       rotation=45, ha="right", fontsize=9)
    ax.set_ylabel("净流入（亿元）", fontsize=11)
    ax.set_title(f"{sector_name} — 资金结构堆叠（按单类型）",
                 fontsize=14, pad=15)
    ax.legend(loc="upper left", fontsize=10)
    plt.tight_layout()
    plt.show()


# ==================== 使用示例 ====================
if __name__ == "__main__":
    # import time
    # start = time.perf_counter()
    # # 1) 获取一个板块的历史数据
    # df_one = fetch_sector_fund_flow_history(
    #     secid="90.BK0438",            # 汽车服务板块
    #     beg="20250801", end="20250917",
    # )
    # fetch_sector_fund_flow_history_time = time.perf_counter() - start
    # plot_single_sector_flow(df_one, sector_name="汽车服务")
    # plot_fund_structure(df_one, sector_name="汽车服务")

    # # # 2) 获取多板块历史数据并对比
    # df_all = fetch_all_sectors_history(
    #     sector_type="industry",
    #     beg="20250801", end="20250917",
    #     inter_sleep=2.0,
    # )
    # fetch_all_sectors_history_time = time.perf_counter() - start - fetch_sector_fund_flow_history_time
    # # 挑几个感兴趣的板块对比
    # plot_multi_sector_flow(
    #     df_all,
    #     sectors=["证券", "银行", "半导体", "光伏设备", "汽车整车"],
    # )

    # # 3) 全市场热力图（Top 20 板块）
    # plot_sector_heatmap(
    #     df_all, top_n=20,
    #     date_range=("2025-08-01", "2025-09-17"),
    # )
    # time_elapsed = time.perf_counter() - start
    # print(f"\n耗时统计: 单板块 {fetch_sector_fund_flow_history_time:.2f}s, 全板块 {fetch_all_sectors_history_time:.2f}s, 总计 {time_elapsed:.2f}s")
    map = fetch_sector_code_map(sector_type="industry")
    print(f"map: {map}")