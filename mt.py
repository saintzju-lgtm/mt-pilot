import streamlit as st
import akshare as ak
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import datetime
import time

# --- 页面配置 ---
st.set_page_config(layout="wide", page_title="AI 智投雷达 (修复版)", page_icon="📡")

# --- CSS 样式优化 ---
st.markdown("""
<style>
    .stTabs [data-baseweb="tab-list"] { gap: 10px; }
    .stTabs [data-baseweb="tab"] { height: 50px; white-space: pre-wrap; background-color: #f0f2f6; border-radius: 4px 4px 0 0; gap: 1px; padding-top: 10px; padding-bottom: 10px; }
    .stTabs [aria-selected="true"] { background-color: #e6f3ff; border-bottom: 2px solid #0068c9; }
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
    "机器人 (概念)": "机器人概念"
}

# --- 1. 数据获取模块 (含市值补全补丁) ---

@st.cache_data(ttl=600)
def fetch_all_market_caps():
    """
    【救生圈函数】获取全市场所有股票的市值，用于补全缺失数据
    """
    try:
        # 获取全市场实时行情 (只取代码和总市值)
        df = ak.stock_zh_a_spot_em()
        df = df[['代码', '总市值']].copy()
        df.rename(columns={'代码': 'code', '总市值': 'mkt_cap_patch'}, inplace=True)
        # 转换为数值
        df['mkt_cap_patch'] = pd.to_numeric(df['mkt_cap_patch'], errors='coerce').fillna(0)
        return df
    except:
        return pd.DataFrame()

@st.cache_data(ttl=600)
def get_stock_list_smart(symbol_name):
    """
    智能获取成分股：双核驱动 + 自动补全市值
    """
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
            if col not in raw_df.columns: 
                raw_df[col] = 0 
                
        final_df = raw_df[required_cols].copy()
        for col in ['price', 'pct_chg', 'mkt_cap', 'volume']:
            final_df[col] = pd.to_numeric(final_df[col], errors='coerce').fillna(0)
            
        return final_df

    # 1. 尝试获取列表 (概念或行业)
    try:
        # 先试概念
        df = ak.stock_board_concept_cons_em(symbol=symbol_name)
        df = clean_data(df)
    except:
        try:
            # 再试行业
            df = ak.stock_board_industry_cons_em(symbol=symbol_name)
            df = clean_data(df)
        except:
            return pd.DataFrame()

    if df.empty: return pd.DataFrame()

    # --- 【关键修复】市值补全逻辑 ---
    # 如果总市值之和为0，说明接口没返回市值，需要去全市场表里查
    if df['mkt_cap'].sum() == 0:
        # print("DEBUG: 检测到市值缺失，正在执行补全...")
        patch_df = fetch_all_market_caps()
        
        if not patch_df.empty:
            # 将补全表合并进来
            df = pd.merge(df, patch_df, on='code', how='left')
            # 用补全的市值覆盖原来的0
            df['mkt_cap'] = df['mkt_cap_patch'].fillna(0)
            # 删除临时列
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
    
    data['MA20'] = data['close'].rolling(window=20).mean()
    data['std'] = data['close'].rolling(window=20).std()
    data['Upper'] = data['MA20'] + (data['std'] * 2)
    data['Lower'] = data['MA20'] - (data['std'] * 2)
    
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
    status_label = "⚪ 观望"
    
    if current_price <= buy_entry * 1.02: 
        status = "buy"
        status_label = "🟢 机会 (低吸)"
    elif current_price >= take_profit * 0.98:
        status = "sell"
        status_label = "🔴 风险 (止盈)"
        
    trend = "多头" if current_price > last['MA20'] else "空头"

    return {
        "status": status,
        "status_label": status_label,
        "trend": trend,
        "buy_entry": buy_entry,
        "take_profit": take_profit,
        "stop_loss": stop_loss,
        "upper_hist": data['Upper'], 
        "lower_hist": data['Lower'],
        "ma20_hist": data['MA20']
    }

# --- 3. 界面逻辑 ---

st.sidebar.title("📡 AI 智投雷达")
selected_theme_label = st.sidebar.radio("1. 选择板块:", list(THEME_MAP.keys()))
real_name = THEME_MAP[selected_theme_label]

st.title(f"📊 板块透视：{selected_theme_label}")

# 步骤 1: 获取名单
with st.spinner(f"正在全网搜索 {real_name} 数据..."):
    df_all = get_stock_list_smart(real_name)

if not df_all.empty:
    # 过滤器
    min_mkt_cap = st.sidebar.slider("2. 最小市值过滤 (亿)", 0, 500, 50)
    
    # --- 修复后的过滤逻辑 ---
    # 检查补全后是否还有数据
    if df_all['mkt_cap'].sum() == 0:
        st.sidebar.error("⚠️ 严重错误：无法获取市值数据，过滤失效。")
        df_filtered = df_all
    else:
        # 正常过滤
        df_filtered = df_all[df_all['mkt_cap'] > (min_mkt_cap * 100000000)].copy()
    
    df_filtered = df_filtered.sort_values(by='pct_chg', ascending=False)
    
    st.markdown(f"**共 {len(df_filtered)} 只股票符合条件。** (点击下方按钮进行AI分类)")
    
    # --- 核心功能：批量扫描 ---
    
    if 'scan_results' not in st.session_state:
        st.session_state.scan_results = None
        st.session_state.last_sector = None

    if st.session_state.last_sector != real_name:
        st.session_state.scan_results = None
        st.session_state.last_sector = real_name
        # 如果切换板块且之前的筛选结果还在，强制刷新一下Session状态里的筛选结果
        st.rerun()

    col_btn, col_info = st.columns([1, 4])
    start_scan = col_btn.button("🚀 开始 AI 深度分类", type="primary")
    
    if start_scan:
        scan_data = {"buy": [], "sell": [], "watch": []}
        scan_list = df_filtered.head(40) 
        
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        total = len(scan_list)
        for i, (index, row) in enumerate(scan_list.iterrows()):
            progress_bar.progress((i + 1) / total)
            status_text.text(f"正在 AI 分析: {row['name']}...")
            
            hist = get_hist_data(row['code'])
            plan = generate_trading_plan(hist, row['price'])
            
            if plan:
                item = {
                    "code": row['code'],
                    "name": row['name'],
                    "price": row['price'],
                    "pct": row['pct_chg'],
                    "buy": plan['buy_entry'],
                    "sell": plan['take_profit'],
                    "trend": plan['trend']
                }
                scan_data[plan['status']].append(item)
            
            time.sleep(0.05)
            
        st.session_state.scan_results = scan_data
        progress_bar.empty()
        status_text.empty()
        st.success("✅ 扫描完成！")

    # --- 展示扫描结果 ---
    if st.session_state.scan_results:
        res = st.session_state.scan_results
        
        tab1, tab2, tab3 = st.tabs([
            f"🟢 黄金低吸区 ({len(res['buy'])})", 
            f"🔴 高危止盈区 ({len(res['sell'])})", 
            f"⚪ 震荡观望区 ({len(res['watch'])})"
        ])
        
        def render_stock_table(stock_list, type_label):
            if not stock_list:
                st.info("无")
                return
            df_res = pd.DataFrame(stock_list)
            st.dataframe(
                df_res,
                column_config={
                    "code": "代码", "name": "名称",
                    "price": st.column_config.NumberColumn("现价", format="¥%.2f"),
                    "pct": st.column_config.NumberColumn("涨幅", format="%.2f%%"),
                    "buy": st.column_config.NumberColumn("支撑位", format="¥%.2f"),
                    "sell": st.column_config.NumberColumn("压力位", format="¥%.2f"),
                    "trend": "趋势"
                },
                hide_index=True, use_container_width=True
            )
        
        with tab1: render_stock_table(res['buy'], "buy")
        with tab2: render_stock_table(res['sell'], "sell")
        with tab3: render_stock_table(res['watch'], "watch")
            
        st.markdown("---")

    # --- 3. 个股详情 ---
    st.subheader("🔎 个股走势验证")
    if len(df_filtered) > 0:
        default_idx = 0
        stock_options = [f"{row['code']} | {row['name']}" for _, row in df_filtered.iterrows()]
        
        selected_stock = st.selectbox("选择股票查看详情:", stock_options, index=default_idx)
        
        if selected_stock:
            code = selected_stock.split(" | ")[0]
            name = selected_stock.split(" | ")[1]
            curr_price = df_filtered[df_filtered['code'] == code].iloc[0]['price']
            
            hist_df = get_hist_data(code)
            if not hist_df.empty:
                plan = generate_trading_plan(hist_df, curr_price)
                if plan:
                    fig = go.Figure()
                    fig.add_trace(go.Candlestick(x=hist_df.index,
                                    open=hist_df['open'], high=hist_df['high'],
                                    low=hist_df['low'], close=hist_df['close'], name='K线'))
                    fig.add_trace(go.Scatter(x=hist_df.index, y=plan['upper_hist'], 
                                             line=dict(color='rgba(200,0,0,0.3)', width=1), name='压力轨'))
                    fig.add_trace(go.Scatter(x=hist_df.index, y=plan['lower_hist'], 
                                             line=dict(color='rgba(0,200,0,0.3)', width=1), name='支撑轨'))
                    
                    fig.add_hline(y=plan['buy_entry'], line_dash="dash", line_color="green", annotation_text="买入")
                    fig.add_hline(y=plan['take_profit'], line_dash="dash", line_color="red", annotation_text="止盈")
                    
                    fig.update_layout(xaxis_rangeslider_visible=False, height=450, 
                                      title=f"{name} - {plan['status_label']}",
                                      margin=dict(l=0, r=0, t=30, b=0))
                    st.plotly_chart(fig, use_container_width=True)

else:
    st.error(f"无法获取板块 [{real_name}] 数据。")
