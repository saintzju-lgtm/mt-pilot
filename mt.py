import streamlit as st
import akshare as ak
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import datetime
import time

# --- 页面配置 ---
st.set_page_config(layout="wide", page_title="AI 智投雷达 (自动分类版)", page_icon="📡")

# --- CSS 优化 ---
st.markdown("""
<style>
    .stTabs [data-baseweb="tab-list"] { gap: 10px; }
    .stTabs [data-baseweb="tab"] { height: 50px; white-space: pre-wrap; background-color: #f0f2f6; border-radius: 4px 4px 0 0; gap: 1px; padding-top: 10px; padding-bottom: 10px; }
    .stTabs [aria-selected="true"] { background-color: #e6f3ff; border-bottom: 2px solid #0068c9; }
</style>
""", unsafe_allow_html=True)

# --- 0. 核心配置 ---
THEME_MAP = {
    "算力/CPO (核心硬件)": "CPO概念",
    "人工智能 (大模型)": "人工智能",
    "半导体 (芯片制造)": "半导体",
    "PCB (印制电路板)": "PCB",
    "英伟达概念": "英伟达概念",
    "存储芯片": "存储芯片",
    "多模态AI": "多模态AI",
    "消费电子": "消费电子",
    "机器人": "机器人概念"
}

# --- 1. 数据获取模块 ---

@st.cache_data(ttl=600)
def get_concept_stocks(concept_name):
    """获取板块成分股"""
    try:
        df = ak.stock_board_concept_cons_em(symbol=concept_name)
        rename_map = {
            '代码': 'code', '名称': 'name', '最新价': 'price', 
            '涨跌幅': 'pct_chg', '成交量': 'volume', '成交额': 'amount',
            '总市值': 'mkt_cap', '总市值(元)': 'mkt_cap', '流通市值': 'mkt_cap' 
        }
        df.rename(columns=rename_map, inplace=True)
        required_cols = ['code', 'name', 'price', 'pct_chg', 'volume', 'mkt_cap']
        for col in required_cols:
            if col not in df.columns: df[col] = 0 
        
        df = df[required_cols]
        for col in ['price', 'pct_chg', 'mkt_cap', 'volume']:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
        return df
    except Exception as e:
        print(f"List Error: {e}")
        return pd.DataFrame()

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
    
    # 指标计算
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
    
    # 策略逻辑
    support = max(last['Lower'], data['low'].tail(20).min())
    resistance = min(last['Upper'], data['high'].tail(20).max())
    
    buy_entry = support * 1.01
    take_profit = resistance * 0.99
    stop_loss = buy_entry - (1.5 * atr)
    
    # 状态判定
    status = "watch" # 默认观望
    status_label = "⚪ 观望"
    if current_price <= buy_entry * 1.02: # 放宽一点点判定范围
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
real_concept_name = THEME_MAP[selected_theme_label]

st.title(f"📊 板块透视：{selected_theme_label}")

# 步骤 1: 获取名单
with st.spinner(f"正在拉取 {real_concept_name} 成分股..."):
    df_all = get_concept_stocks(real_concept_name)

if not df_all.empty:
    # 过滤器
    min_mkt_cap = st.sidebar.slider("2. 最小市值过滤 (亿)", 0, 500, 30)
    
    if df_all['mkt_cap'].sum() == 0:
        st.sidebar.warning("⚠️ 市值数据缺失，显示全部")
        df_filtered = df_all
    else:
        df_filtered = df_all[df_all['mkt_cap'] > (min_mkt_cap * 100000000)].copy()
    
    df_filtered = df_filtered.sort_values(by='pct_chg', ascending=False)
    
    st.markdown(f"**共 {len(df_filtered)} 只股票符合条件。** (点击下方按钮进行AI分类)")
    
    # --- 核心功能：批量扫描 ---
    
    # 使用 Session State 保存扫描结果，防止刷新丢失
    if 'scan_results' not in st.session_state:
        st.session_state.scan_results = None
        st.session_state.last_sector = None

    # 如果切换了板块，清空之前的扫描结果
    if st.session_state.last_sector != real_concept_name:
        st.session_state.scan_results = None
        st.session_state.last_sector = real_concept_name

    col_btn, col_info = st.columns([1, 4])
    start_scan = col_btn.button("🚀 开始 AI 深度分类", type="primary")
    
    # 扫描逻辑
    if start_scan:
        scan_data = {"buy": [], "sell": [], "watch": []}
        
        # 限制最大扫描数量，防止等待太久 (例如取前30只龙头)
        # 如果你想全扫，可以去掉这个切片，但会很慢
        scan_list = df_filtered.head(40) 
        
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        total = len(scan_list)
        for i, (index, row) in enumerate(scan_list.iterrows()):
            # 更新进度
            progress_bar.progress((i + 1) / total)
            status_text.text(f"正在分析: {row['name']} ({i+1}/{total})...")
            
            # 获取历史并计算
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
            
            # 极小延时防止接口封禁
            time.sleep(0.05)
            
        st.session_state.scan_results = scan_data
        progress_bar.empty()
        status_text.empty()
        st.success("✅ 扫描完成！已自动分类。")

    # --- 展示扫描结果 ---
    if st.session_state.scan_results:
        res = st.session_state.scan_results
        
        # 定义三个 Tab
        tab1, tab2, tab3 = st.tabs([
            f"🟢 黄金低吸区 ({len(res['buy'])})", 
            f"🔴 高危止盈区 ({len(res['sell'])})", 
            f"⚪ 震荡观望区 ({len(res['watch'])})"
        ])
        
        # 渲染函数的通用逻辑
        def render_stock_table(stock_list, type_label):
            if not stock_list:
                st.info("当前分类下暂无股票。")
                return
            
            # 转为 DataFrame 展示
            df_res = pd.DataFrame(stock_list)
            
            # 配置列显示
            st.dataframe(
                df_res,
                column_config={
                    "code": "代码", "name": "名称",
                    "price": st.column_config.NumberColumn("现价", format="¥%.2f"),
                    "pct": st.column_config.NumberColumn("今日涨幅", format="%.2f%%"),
                    "buy": st.column_config.NumberColumn("支撑位(买)", format="¥%.2f"),
                    "sell": st.column_config.NumberColumn("压力位(卖)", format="¥%.2f"),
                    "trend": "趋势"
                },
                hide_index=True,
                use_container_width=True
            )
        
        with tab1:
            st.markdown("##### 👇 价格已回落至支撑位附近，盈亏比较高")
            render_stock_table(res['buy'], "buy")
            
        with tab2:
            st.markdown("##### 👇 价格已触及布林带上轨，追高风险大")
            render_stock_table(res['sell'], "sell")
            
        with tab3:
            st.markdown("##### 👇 价格位于通道中间，建议多看少动")
            render_stock_table(res['watch'], "watch")
            
        st.markdown("---")

    # --- 3. 个股详情 (保留，用于Deep Dive) ---
    st.subheader("🔎 个股深度透视")
    if len(df_filtered) > 0:
        # 默认选中第一个“低吸”的股票，如果没有则选第一个
        default_idx = 0
        stock_options = [f"{row['code']} | {row['name']}" for _, row in df_filtered.iterrows()]
        
        selected_stock = st.selectbox("选择股票查看走势图:", stock_options, index=default_idx)
        
        if selected_stock:
            code = selected_stock.split(" | ")[0]
            name = selected_stock.split(" | ")[1]
            curr_price = df_filtered[df_filtered['code'] == code].iloc[0]['price']
            
            hist_df = get_hist_data(code)
            if not hist_df.empty:
                plan = generate_trading_plan(hist_df, curr_price)
                if plan:
                    # 画图
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
    st.error("无法获取板块数据，请稍后重试。")
