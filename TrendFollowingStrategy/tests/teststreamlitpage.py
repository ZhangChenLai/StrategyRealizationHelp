# app.py
import json
import math
import random
import time
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st
from curl_cffi import requests

import matplotlib
import matplotlib.pyplot as plt

# ============================================================
# 全局配置
# ============================================================
st.set_page_config(
    page_title="板块资金流监控",
    page_icon="📊",
    layout="wide",
)

matplotlib.rcParams['font.sans-serif'] = [
    'SimHei', 'Microsoft YaHei', 'PingFang SC',
    'Heiti SC', 'Arial Unicode MS', 'DejaVu Sans',
]
matplotlib.rcParams['axes.unicode_minus'] = False
matplotlib.rcParams['figure.dpi'] = 100

PUSH2_URL     = "https://push2.eastmoney.com/api/qt/clist/get"
PUSH2HIS_URL  = "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get"

_FS_MAP = {"industry": "m:90 t:2", "concept": "m:90 t:3"}
_FIELDS = "f12,f14,f3,f62,f184,f66,f72,f78,f84"

# 🔑 从 cookie.txt 读取 Cookie
COOKIE_FILE = Path(__file__).parent / "cookie.txt"
COOKIE_STR = COOKIE_FILE.read_text(encoding="utf-8").strip() if COOKIE_FILE.exists() else ""

_HEADERS = {
    "Accept": "*/*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": "https://data.eastmoney.com/",
    "Cookie": COOKIE_STR,
}

_PAGE_SIZE = 100
_MAX_RETRIES = 3


# ============================================================
# 数据获取（与之前一致，稍作整理）
# ============================================================
def _build_session() -> requests.Session:
    s = requests.Session(impersonate="chrome124")
    s.headers.update(_HEADERS)
    return s


def _clean_json(text: str) -> str:
    if text.startswith("jQuery") or text.startswith("("):
        text = text[text.index("(") + 1: text.rindex(")")]
    return text


def _to_float(v):
    if v in (None, "-", ""):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _request_page(session, sector_type, page, timeout=15.0):
    params = {
        "pn": str(page), "pz": str(_PAGE_SIZE),
        "po": "1", "np": "1",
        "ut": "b2884a393a59ad64002292a3e90d46a5",
        "fltt": "2", "invt": "2",
        "fid": "f62",
        "fs": _FS_MAP[sector_type],
        "fields": _FIELDS,
        "_": int(time.time() * 1000),
    }
    last = None
    for attempt in range(_MAX_RETRIES):
        try:
            if attempt > 0:
                time.sleep(1.5 ** attempt)
            r = session.get(PUSH2_URL, params=params, timeout=timeout)
            r.raise_for_status()
            return json.loads(_clean_json(r.text))
        except Exception as e:
            last = e
    raise RuntimeError(f"page={page} 失败: {last}")


def fetch_sector_fund_flow(sector_type="industry") -> pd.DataFrame:
    session = _build_session()
    try:
        first = _request_page(session, sector_type, 1)
        data = first.get("data") or {}
        total = data.get("total") or 0
        pages = max(1, math.ceil(total / _PAGE_SIZE))

        diff = data.get("diff") or []
        if isinstance(diff, dict):
            diff = list(diff.values())
        rows = list(diff)

        for page in range(2, pages + 1):
            time.sleep(1.5 + random.uniform(0, 1.0))
            try:
                j = _request_page(session, sector_type, page)
            except RuntimeError:
                continue
            d = (j.get("data") or {}).get("diff") or []
            if isinstance(d, dict):
                d = list(d.values())
            rows.extend(d)
    finally:
        session.close()

    seen, recs = set(), []
    for r in rows:
        code, name = r.get("f12"), r.get("f14")
        if not code or not name or code in seen:
            continue
        seen.add(code)
        recs.append({
            "code": code, "name": name,
            "pct_chg": _to_float(r.get("f3")),
            "main_net": _to_float(r.get("f62")),
            "main_net_rate": _to_float(r.get("f184")),
            "super_net": _to_float(r.get("f66")),
            "big_net": _to_float(r.get("f72")),
            "mid_net": _to_float(r.get("f78")),
            "small_net": _to_float(r.get("f84")),
        })
    df = pd.DataFrame(recs)
    for c in ["main_net", "super_net", "big_net", "mid_net", "small_net"]:
        if c in df.columns:
            df[c] = df[c] / 1e8
    return df


def fetch_sector_fund_flow_history(secid, beg, end, klt=101) -> pd.DataFrame:
    params = {
        "secid": secid,
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "klt": str(klt), "fqt": "1",
        "beg": beg, "end": end, "lmt": "1000",
        "_": int(time.time() * 1000),
    }
    with _build_session() as s:
        r = s.get(PUSH2HIS_URL, params=params, timeout=15)
        r.raise_for_status()
    data = json.loads(_clean_json(r.text))
    klines = (data.get("data") or {}).get("klines") or []

    recs = []
    for line in klines:
        p = line.split(",")
        if len(p) < 11:
            continue
        recs.append({
            "date": pd.to_datetime(p[0]),
            "main_net": float(p[1]) / 1e8,
            "small_net": float(p[2]) / 1e8,
            "mid_net": float(p[3]) / 1e8,
            "big_net": float(p[4]) / 1e8,
            "super_net": float(p[5]) / 1e8,
            "main_net_rate": float(p[6]),
            "small_net_rate": float(p[7]),
            "mid_net_rate": float(p[8]),
            "big_net_rate": float(p[9]),
            "super_net_rate": float(p[10]),
        })
    df = pd.DataFrame(recs)
    if not df.empty:
        df = df.sort_values("date").reset_index(drop=True)
    return df


def fetch_sector_code_map(sector_type="industry") -> dict:
    params = {
        "pn": "1", "pz": "500", "po": "1", "np": "1",
        "ut": "b2884a393a59ad64002292a3e90d46a5",
        "fltt": "2", "invt": "2", "fid": "f62",
        "fs": _FS_MAP[sector_type],
        "fields": "f12,f14",
        "_": int(time.time() * 1000),
    }
    with _build_session() as s:
        r = s.get(PUSH2_URL, params=params, timeout=15)
    data = json.loads(_clean_json(r.text))
    diff = (data.get("data") or {}).get("diff") or []
    return {row["f14"]: f"90.{row['f12']}" for row in diff}


def fetch_all_sectors_history(sector_type="industry", beg="20250801",
                              end="20250917", inter_sleep=1.5,
                              progress_cb=None) -> pd.DataFrame:
    code_map = fetch_sector_code_map(sector_type)
    all_dfs = []
    total = len(code_map)
    for i, (name, secid) in enumerate(code_map.items(), 1):
        try:
            df = fetch_sector_fund_flow_history(secid, beg, end)
            if not df.empty:
                df.insert(0, "sector_name", name)
                df.insert(1, "secid", secid)
                all_dfs.append(df)
        except Exception as e:
            print(f"[{name}] 失败: {e}")
        if progress_cb:
            progress_cb(i, total, name)
        time.sleep(inter_sleep)
    return pd.concat(all_dfs, ignore_index=True) if all_dfs else pd.DataFrame()


# ============================================================
# 缓存层（Streamlit 会缓存这些结果，避免重复请求）
# ============================================================
@st.cache_data(show_spinner=False, ttl=3600)
def cached_sector_code_map(sector_type: str) -> dict:
    return fetch_sector_code_map(sector_type)


@st.cache_data(show_spinner=False, ttl=3600)
def cached_single_history(secid: str, beg: str, end: str) -> pd.DataFrame:
    return fetch_sector_fund_flow_history(secid, beg, end)


@st.cache_data(show_spinner=False, ttl=3600)
def cached_all_history(sector_type: str, beg: str, end: str) -> pd.DataFrame:
    return fetch_all_sectors_history(sector_type, beg, end, inter_sleep=1.5)


# ============================================================
# 绘图函数（返回 fig，供 st.pyplot 渲染）
# ============================================================
def fig_single_sector_flow(df, sector_name="板块"):
    d = df.sort_values("date").reset_index(drop=True).copy()
    d["cum_main_net"] = d["main_net"].cumsum()

    fig, ax1 = plt.subplots(figsize=(13, 5.5))
    colors = ["#d62728" if v >= 0 else "#2ca02c" for v in d["main_net"]]
    ax1.bar(d["date"], d["main_net"], color=colors, alpha=0.8,
            width=0.7, label="每日主力净流入")
    ax1.axhline(0, color="gray", linewidth=0.8, linestyle="--")
    ax1.set_ylabel("每日主力净流入（亿元）", fontsize=11)

    ax2 = ax1.twinx()
    ax2.plot(d["date"], d["cum_main_net"], color="#1f77b4",
             linewidth=2.0, marker="o", markersize=3.5, label="累计净流入")
    ax2.set_ylabel("累计主力净流入（亿元）", fontsize=11, color="#1f77b4")
    ax2.tick_params(axis="y", labelcolor="#1f77b4")

    h1, l1 = ax1.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax1.legend(h1 + h2, l1 + l2, loc="upper left", fontsize=10)

    ax1.set_title(f"{sector_name} — 每日主力净流入与累计趋势", fontsize=14, pad=12)
    fig.autofmt_xdate(rotation=45)
    fig.tight_layout()
    return fig


def fig_multi_sector_flow(df_all, sectors):
    fig, ax = plt.subplots(figsize=(13, 5.5))
    for name in sectors:
        sub = df_all[df_all["sector_name"] == name].sort_values("date")
        if sub.empty:
            continue
        ax.plot(sub["date"], sub["main_net"].cumsum(),
                linewidth=2.0, marker="o", markersize=3, label=name)
    ax.axhline(0, color="gray", linewidth=0.8, linestyle="--")
    ax.set_ylabel("累计主力净流入（亿元）", fontsize=11)
    ax.set_title("多板块累计主力净流入对比", fontsize=14, pad=12)
    ax.legend(loc="best", fontsize=10, ncol=2)
    fig.autofmt_xdate(rotation=45)
    fig.tight_layout()
    return fig


def fig_sector_heatmap(df_all, top_n=20, date_range=None):
    d = df_all.copy()
    d["date"] = pd.to_datetime(d["date"])
    if date_range:
        d = d[(d["date"] >= pd.to_datetime(date_range[0])) &
              (d["date"] <= pd.to_datetime(date_range[1]))]

    rank = (d.groupby("sector_name")["main_net"].sum()
              .sort_values(ascending=False).head(top_n).index.tolist())
    d = d[d["sector_name"].isin(rank)]

    pivot = d.pivot_table(index="sector_name", columns="date",
                          values="main_net", aggfunc="sum").reindex(rank)

    fig, ax = plt.subplots(figsize=(13, max(6, top_n * 0.4)))
    vmax = np.nanmax(np.abs(pivot.values)) if pivot.size else 1
    im = ax.imshow(pivot.values, aspect="auto", cmap="RdYlGn_r",
                   vmin=-vmax, vmax=vmax)
    ax.set_xticks(range(len(pivot.columns)))
    ax.set_xticklabels([c.strftime("%m-%d") for c in pivot.columns],
                       rotation=45, ha="right", fontsize=9)
    ax.set_yticks(range(len(pivot.index)))
    ax.set_yticklabels(pivot.index, fontsize=9)
    cbar = fig.colorbar(im, ax=ax, fraction=0.025, pad=0.02)
    cbar.set_label("主力净流入（亿元）", fontsize=10)
    ax.set_title(f"板块资金流热力图（Top {top_n}）", fontsize=14, pad=12)
    fig.tight_layout()
    return fig


def fig_fund_structure(df, sector_name="板块"):
    d = df.sort_values("date").reset_index(drop=True).copy()
    fig, ax = plt.subplots(figsize=(13, 5.5))
    x = np.arange(len(d))
    ax.bar(x, d["super_net"], color="#c0392b", label="超大单", width=0.7)
    ax.bar(x, d["big_net"], bottom=d["super_net"],
           color="#e67e22", label="大单", width=0.7)
    ax.bar(x, d["mid_net"], bottom=d["super_net"] + d["big_net"],
           color="#95a5a6", label="中单", width=0.7)
    ax.bar(x, d["small_net"],
           bottom=d["super_net"] + d["big_net"] + d["mid_net"],
           color="#27ae60", label="小单", width=0.7)
    ax.axhline(0, color="black", linewidth=0.8, linestyle="--")

    step = max(1, len(x) // 15)
    ax.set_xticks(x[::step])
    ax.set_xticklabels([d["date"].iloc[i].strftime("%m-%d")
                        for i in range(0, len(x), step)],
                       rotation=45, ha="right", fontsize=9)
    ax.set_ylabel("净流入（亿元）", fontsize=11)
    ax.set_title(f"{sector_name} — 资金结构堆叠", fontsize=14, pad=12)
    ax.legend(loc="upper left", fontsize=10)
    fig.tight_layout()
    return fig


# ============================================================
# Streamlit 界面
# ============================================================
st.title("📊 板块资金流监控")
if not COOKIE_STR:
    st.warning("未检测到 cookie.txt，若接口被拦截，请把浏览器里的 Cookie 写入 cookie.txt 后重试。")

# ---------- 侧边栏 ----------
with st.sidebar:
    st.header("⚙️ 参数设置")

    sector_type_label = st.radio("板块类型", ["行业板块", "概念板块"], index=0)
    sector_type = "industry" if sector_type_label == "行业板块" else "concept"

    today = pd.Timestamp.today()
    default_beg = (today - pd.Timedelta(days=45)).strftime("%Y%m%d")
    default_end = today.strftime("%Y%m%d")

    col1, col2 = st.columns(2)
    with col1:
        beg = st.text_input("开始日期", value=default_beg,
                            help="格式 YYYYMMDD")
    with col2:
        end = st.text_input("结束日期", value=default_end,
                            help="格式 YYYYMMDD")

    st.divider()
    top_n = st.slider("热力图板块数量", 10, 40, 20, step=5)

    st.divider()
    if st.button("🔄 清空缓存", use_container_width=True):
        st.cache_data.clear()
        st.success("缓存已清空")
        st.rerun()


# ---------- 板块代码表 ----------
with st.spinner("加载板块列表..."):
    try:
        code_map = cached_sector_code_map(sector_type)
    except Exception as e:
        st.error(f"获取板块列表失败: {e}")
        st.stop()

sector_names = list(code_map.keys())


# ---------- Tabs ----------
tab1, tab2, tab3, tab4 = st.tabs(
    ["📈 单板块趋势", "🆚 多板块对比", "🔥 板块热力图", "🧬 资金结构"]
)


# ========== Tab 1：单板块趋势 ==========
with tab1:
    st.subheader("单板块资金流趋势")
    sel_name = st.selectbox("选择板块", sector_names, index=0, key="single_name")

    if st.button("查询该板块", key="btn_single"):
        try:
            with st.spinner(f"正在获取「{sel_name}」的历史数据..."):
                df_one = cached_single_history(code_map[sel_name], beg, end)
            if df_one.empty:
                st.warning("未获取到数据，请检查日期范围或 Cookie 是否有效。")
            else:
                st.pyplot(fig_single_sector_flow(df_one, sector_name=sel_name))
                with st.expander("查看原始数据"):
                    st.dataframe(df_one, use_container_width=True)
        except Exception as e:
            st.error(f"获取失败: {e}")


# ========== Tab 2 & 3 依赖全量数据 ==========
with tab2:
    st.subheader("多板块累计净流入对比")
    st.caption("首次加载全量板块数据较慢（约 1-3 分钟），之后会走缓存。")

    default_pick = [n for n in ["证券", "银行", "半导体", "光伏设备", "汽车整车"]
                    if n in sector_names]
    picked = st.multiselect("选择要对比的板块", sector_names, default=default_pick)

    if st.button("加载全量数据并绘图", key="btn_multi"):
        if not picked:
            st.warning("请至少选择一个板块。")
        else:
            prog = st.progress(0.0, text="正在加载全量板块数据...")
            def _cb(i, total, name):
                prog.progress(i / total, text=f"[{i}/{total}] {name}")
            try:
                df_all = cached_all_history(sector_type, beg, end)
                prog.empty()
            except Exception as e:
                prog.empty()
                st.error(f"加载失败: {e}")
                st.stop()

            st.session_state["df_all"] = df_all
            st.pyplot(fig_multi_sector_flow(df_all, picked))

    # 复用已加载的全量数据
    if "df_all" in st.session_state and st.session_state["df_all"] is not None:
        df_all = st.session_state["df_all"]
        st.caption(f"已缓存全量数据：{len(df_all)} 行，"
                   f"{df_all['sector_name'].nunique()} 个板块")


with tab3:
    st.subheader("板块资金流热力图")

    if "df_all" not in st.session_state or st.session_state["df_all"] is None:
        st.info("请先在「多板块对比」标签页点击「加载全量数据并绘图」。")
    else:
        df_all = st.session_state["df_all"]
        st.pyplot(
            fig_sector_heatmap(df_all, top_n=top_n,
                               date_range=(pd.to_datetime(beg), pd.to_datetime(end)))
        )


# ========== Tab 4：资金结构 ==========
with tab4:
    st.subheader("资金结构堆叠（超大单 / 大单 / 中单 / 小单）")
    sel_name2 = st.selectbox("选择板块", sector_names, index=0, key="struct_name")

    if st.button("查询资金结构", key="btn_struct"):
        try:
            with st.spinner(f"正在获取「{sel_name2}」..."):
                df_one = cached_single_history(code_map[sel_name2], beg, end)
            if df_one.empty:
                st.warning("未获取到数据。")
            else:
                st.pyplot(fig_fund_structure(df_one, sector_name=sel_name2))
        except Exception as e:
            st.error(f"获取失败: {e}")