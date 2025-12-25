import streamlit as st
import akshare as ak
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import datetime
import time

# --- 页面配置 ---
st.set_page_config(layout="wide", page_title="AI 量化实盘监控", page_icon="⚡")

# --- CSS 样式优化 (红绿涨跌色) ---
st.markdown("""
<style>
    .big-font { font-size: 20px !important; font-weight: bold; }
    .buy-signal { background-color: #d4edda; padding: 10px; border-radius: 5px; border-left: 5px solid #28a745; }
    .stDataFrame { font-size: 14px; }
</style>
""", unsafe_allow_html=True)

# --- 0. 核心配置 ---
THEME_MAP = {
    "算力/CPO (概念)": "CPO概念",
    "人工智能 (概念)": "人工智能",
    "半导体 (行业)": "半导体",        
    "存储芯片 (概念)": "存储芯片",
    "PCB (行业)": "印制电路板",       
    "英伟达概念": "英伟达概念",
    "消费电子 (行业)": "消费电子",
    "机器人 (概念)": "机器人概念",
    "低空经济 (概念)": "低空经济"
}

# --- 1. 数据获取模块 ---

@st.cache_data(ttl=600)
def fetch_all_market_caps():
    """市值补全补丁"""
    try:
        df = ak.stock_zh_a_spot_em()
        df = df[['代码', '总市值']].copy()
        df.rename(columns={'代码': 'code', '总市值': 'mkt_cap_patch'}, inplace=True)
        df['mkt_cap_patch'] = pd.to_numeric(df['mkt_cap_patch'], errors='coerce').fillna(0)
        return df
    except:
        return pd.DataFrame()

@st.cache_data(ttl=300) # 列表缓存5分钟
def get_stock_list_smart(symbol_name):
    """智能获取成分股"""
    df = pd.DataFrame()
    
    def clean_data(raw_df):
        if raw_df.empty: return pd.DataFrame()
        rename_map = {
            '代码': 'code', '名称': 'name', '最新价': 'price', 
            '涨跌幅': 'pct_chg', '成交量': 'volume', '成交额': 'amount',
            '总市值': 'mkt_cap', '总市值(元)': 'mkt_cap', '流通市值': 'mkt_cap' 
        }
        raw_df.rename(columns=rename_map, inplace=True)
        required_cols = ['code', 'name', 'price', 'pct_chg', 'volume', 'mkt_cap']
        for col in required_cols:
            if col not in raw_df.columns: raw_df[col] = 0 
        final_df = raw_df[required_cols].copy()
        for col in ['price', 'pct_chg', 'mkt_cap', 'volume']:
            final_df[col] = pd.to_numeric(final_df[col], errors='coerce').fillna(0)
        return final_df

    try:
        df = ak.stock_board_concept_cons_em(symbol=symbol_name)
        df = clean_data(df)
    except:
        try:
            df = ak.stock_board_industry_cons_em(symbol=symbol_name)
            df = clean_data(df)
        except:
            return pd.DataFrame()

    if df.empty: return pd.DataFrame()

    # 市值补全
    if df['mkt_cap'].sum() == 0:
        patch_df = fetch_all_market_caps()
        if not patch_df.empty:
            df = pd.merge(df, patch_df, on='code', how='left')
            df['mkt_cap'] = df['mkt_cap_patch'].fillna(0)
            df.drop(columns=['mkt_cap_patch'], inplace=True)
            
    return df

@st.cache_data(ttl=3600)
def get_hist_data(code):
    """获取历史K线"""
    end_date = datetime.datetime.now().strftime("%Y%m%d")
    start_date = (datetime.datetime.now() - datetime.timedelta(days=180)).strftime("%Y%m%d")
    try:
        df = ak.stock_zh_a_hist(symbol=code, period="daily", start_date=start_date, end_date=end_date, adjust="qfq")
        if df.empty: return pd.DataFrame()
        df.rename(columns={'日期': 'date', '开盘': 'open', '收盘': 'close', '最高': 'high', '最低': 'low', '成交量': 'volume'}, inplace=True)
        df['date'] = pd.to_datetime(df['date'])
        df.set_index('date', inplace=True)
        return df
    except:
        return pd.DataFrame()

# --- 2. 核心算法 ---
def generate_trading_plan(df, current_price):
    if df.empty or len(df) < 20: return None
    data = df.copy()
    
    # 布林带
    data['MA20'] = data['close'].rolling(window=20).mean()
    data['std'] = data['close'].rolling(window=20).std()
    data['Upper'] = data['MA20'] + (data['std'] * 2)
    data['Lower'] = data['MA20'] - (data['std'] * 2)
    
    # ATR
    data['tr'] = np.maximum((data['high'] - data['low']), 
                            np.maximum(abs(data['high'] - data['close'].shift(1)), 
                                       abs(data['low'] - data['close'].shift(1))))
    atr = data['tr'].rolling(window=14).mean().iloc[-1]
    
    last = data.iloc[-1]
    
    support = max(last['Lower'], data['low'].tail(20).min())
    resistance = min(last['Upper'], data['high'].tail(20).max())
    
    buy_entry = support * 1.01
    take_profit = resistance * 0.99
    stop_loss = buy_entry - (1.5 * atr)
    
    status = "watch"
    
    # 策略核心：价格跌破支撑位附近 +1%
    if current_price <= buy_entry * 1.02: 
        status = "buy"
    elif current_price >= take_profit * 0.98:
        status = "sell"
        
    trend = "多头" if current_price > last['MA20'] else "空头"

    return {
        "status": status,
        "trend": trend,
        "buy_entry": buy_entry,
        "take_profit": take_profit,
        "stop_loss": stop_loss,
        "upper_hist": data['Upper'], 
        "lower_hist": data['Lower']
    }

# --- 3. 界面逻辑 ---

# 侧边栏设置
st.sidebar.header("🕹️ 监控设置")
selected_theme_label = st.sidebar.selectbox("1. 监控板块:", list(THEME_MAP.keys()))
real_name = THEME_MAP[selected_theme_label]

min_mkt_cap = st.sidebar.slider("2. 最小市值 (亿)", 0, 500, 50)
scan_limit = st.sidebar.slider("3. 扫描龙头数量 (越少越快)", 10, 100, 30, help="为了保证10秒刷新，建议只扫描前30-50只龙头")

st.sidebar.markdown("---")
auto_refresh = st.sidebar.toggle("⚡ 开启 10s 自动刷新", value=False)

# 标题区
st.title(f"⚡ AI 量化实盘监控：{selected_theme_label}")
if auto_refresh:
    st.caption(f"🟢 监控运行中... 每 10 秒刷新一次 | 扫描范围: Top {scan_limit} 活跃股")
else:
    st.caption("🔴 监控暂停 | 请开启侧边栏开关以启动实时刷新")

# 主逻辑
df_all = get_stock_list_smart(real_name)

if not df_all.empty:
    # 过滤与排序
    if df_all['mkt_cap'].sum() == 0:
        df_filtered = df_all
    else:
        df_filtered = df_all[df_all['mkt_cap'] > (min_mkt_cap * 100000000)].copy()
    
    # 按【成交额】排序，优先看活跃的龙头，而不是按涨幅
    # 这样能保证你看到的都是有流动性的票
    if 'amount' in df_filtered.columns:
        df_filtered = df_filtered.sort_values(by='amount', ascending=False)
    else:
        df_filtered = df_filtered.sort_values(by='pct_chg', ascending=False)
    
    # 截取前 N 只进行扫描
    scan_list = df_filtered.head(scan_limit)
    
    # --- 核心扫描逻辑 ---
    # 如果开启自动刷新，或者没有缓存结果，就执行扫描
    should_scan = True
    
    if should_scan:
        buy_signals = []
        
        # 进度条容器 (仅在非自动模式下显示，避免闪烁)
        if not auto_refresh:
            progress_bar = st.progress(0)
        
        total = len(scan_list)
        for i, (index, row) in enumerate(scan_list.iterrows()):
            if not auto_refresh:
                progress_bar.progress((i + 1) / total)
            
            # 获取数据
            hist = get_hist_data(row['code'])
            plan = generate_trading_plan(hist, row['price'])
            
            if plan and plan['status'] == "buy":
                # 计算量化操作建议
                profit_space = (plan['take_profit'] - plan['buy_entry']) / plan['buy_entry'] * 100
                
                buy_signals.append({
                    "代码": row['code'],
                    "名称": row['name'],
                    "现价": row['price'],
                    "涨幅": f"{row['pct_chg']:.2f}%",
                    "🎯 低吸挂单价": f"¥{plan['buy_entry']:.2f}",
                    "🛑 止损价": f"¥{plan['stop_loss']:.2f}",
                    "🚀 目标止盈": f"¥{plan['take_profit']:.2f}",
                    "理论盈亏比": f"{profit_space:.1f}%",
                    "趋势": plan['trend']
                })
        
        if not auto_refresh:
            progress_bar.empty()

        # --- 结果展示区 (置顶) ---
        
        # 1. 🚨 黄金低吸名单 (最重要!)
        if buy_signals:
            st.markdown(f"### 🚨 发现 {len(buy_signals)} 个低吸机会 (立即关注)")
            st.markdown("""
            <div class="buy-signal">
            <b>💡 量化操作指南：</b><br>
            1. <b>低吸挂单价</b>：建议在券商APP以此价格埋伏挂单（Limit Order）。<br>
            2. <b>止损价</b>：收盘价若跌破此价格，建议无脑离场。<br>
            3. <b>盈亏比</b>：数值越大，这笔交易越划算。
            </div>
            """, unsafe_allow_html=True)
            
            st.table(pd.DataFrame(buy_signals)) # 使用 Table 展示更清晰
        else:
            st.info("🍵 当前扫描范围内暂无【低吸】信号，行情可能在高位或中间态，建议观望。")

        st.markdown("---")

        # 2. 实时行情概览 (为了不让下面太空)
        st.subheader("📋 活跃龙头监控 (Top List)")
        st.dataframe(
            scan_list[['code', 'name', 'price', 'pct_chg', 'mkt_cap']],
            column_config={
                "code": "代码", "name": "名称", 
                "price": st.column_config.NumberColumn("现价", format="¥%.2f"),
                "pct_chg": st.column_config.NumberColumn("涨幅", format="%.2f%%"),
                "mkt_cap": st.column_config.NumberColumn("市值", format="¥%.0f")
            },
            hide_index=True, use_container_width=True, height=300
        )

    # --- 自动刷新逻辑 ---
    if auto_refresh:
        time.sleep(10) # 等待10秒
        st.rerun()     # 重新运行整个脚本

else:
    st.error(f"无法获取 {real_name} 数据，请检查网络或稍后重试。")
