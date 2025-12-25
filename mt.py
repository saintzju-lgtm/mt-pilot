import streamlit as st
import akshare as ak
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import datetime

# --- 页面配置 ---
st.set_page_config(layout="wide", page_title="AI 全产业链雷达 (最终版)", page_icon="📡")

# --- 0. 核心配置：定义要抓取的主题板块 ---
THEME_MAP = {
    "算力/CPO (核心硬件)": "CPO概念",
    "人工智能 (大模型/应用)": "人工智能",
    "半导体 (芯片制造)": "半导体",
    "PCB (印制电路板)": "PCB",
    "英伟达概念 (供应链)": "英伟达概念",
    "存储芯片": "存储芯片",
    "多模态AI": "多模态AI"
}

# --- 1. 数据获取模块 (高容错版) ---

@st.cache_data(ttl=600)
def get_concept_stocks(concept_name):
    """
    抓取指定概念板块下的【所有】股票及实时行情 (自动适配列名，防止报错)
    """
    try:
        # 接口：东方财富-概念板块-板块成分
        df = ak.stock_board_concept_cons_em(symbol=concept_name)
        
        # 1. 建立列名映射字典 (适配接口可能的变动)
        rename_map = {
            '代码': 'code', '名称': 'name', '最新价': 'price', 
            '涨跌幅': 'pct_chg', '成交量': 'volume', '成交额': 'amount',
            '总市值': 'mkt_cap', '总市值(元)': 'mkt_cap', '流通市值': 'mkt_cap' 
        }
        
        # 2. 重命名存在的列
        df.rename(columns=rename_map, inplace=True)
        
        # 3. 补全关键列 (防止 Key Error)
        required_cols = ['code', 'name', 'price', 'pct_chg', 'volume', 'mkt_cap']
        for col in required_cols:
            if col not in df.columns:
                df[col] = 0 # 缺失填充为 0
        
        # 4. 筛选与清洗
        df = df[required_cols]
        for col in ['price', 'pct_chg', 'mkt_cap', 'volume']:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
            
        return df
        
    except Exception as e:
        print(f"数据获取错误: {e}")
        return pd.DataFrame()

@st.cache_data(ttl=3600)
def get_hist_data(code):
    """
    获取个股历史K线 (前复权)
    """
    end_date = datetime.datetime.now().strftime("%Y%m%d")
    start_date = (datetime.datetime.now() - datetime.timedelta(days=180)).strftime("%Y%m%d")
    
    try:
        df = ak.stock_zh_a_hist(symbol=code, period="daily", start_date=start_date, end_date=end_date, adjust="qfq")
        if df.empty: return pd.DataFrame()
            
        df.rename(columns={'日期': 'date', '开盘': 'open', '收盘': 'close', '最高': 'high', '最低': 'low', '成交量': 'volume'}, inplace=True)
        df['date'] = pd.to_datetime(df['date'])
        df.set_index('date', inplace=True)
        return df
    except Exception:
        return pd.DataFrame()

# --- 2. 核心算法：生成实战建议 (修复了返回值，包含历史序列) ---
def generate_trading_plan(df, current_price):
    if df.empty or len(df) < 20:
        return None

    data = df.copy()
    
    # 计算技术指标
    data['MA20'] = data['close'].rolling(window=20).mean()
    data['std'] = data['close'].rolling(window=20).std()
    data['Upper'] = data['MA20'] + (data['std'] * 2)
    data['Lower'] = data['MA20'] - (data['std'] * 2)
    
    # ATR 计算
    data['tr'] = np.maximum((data['high'] - data['low']), 
                            np.maximum(abs(data['high'] - data['close'].shift(1)), 
                                       abs(data['low'] - data['close'].shift(1))))
    atr = data['tr'].rolling(window=14).mean().iloc[-1]
    
    # 取最新一天的数据用于计算点位
    last_row = data.iloc[-1]
    
    # 策略点位计算
    support_level = max(last_row['Lower'], data['low'].tail(20).min())
    resistance_level = min(last_row['Upper'], data['high'].tail(20).max())
    
    buy_entry = support_level * 1.01
    take_profit = resistance_level * 0.99
    stop_loss = buy_entry - (1.5 * atr)
    
    # 趋势判定
    trend = "震荡"
    if current_price > last_row['MA20']:
        trend = "多头趋势 (MA20上方)"
    else:
        trend = "空头趋势 (MA20下方)"
        
    return {
        # 文字建议用的数值 (Scalar)
        "trend": trend,
        "buy_entry": buy_entry,
        "take_profit": take_profit,
        "stop_loss": stop_loss,
        
        # 画图用的完整序列 (Series) - 这里是修复的关键
        "upper_hist": data['Upper'], 
        "lower_hist": data['Lower'],
        "ma20_hist": data['MA20']
    }

# --- 3. 界面逻辑 ---

st.sidebar.title("📡 AI 全产业链扫描")
selected_theme_label = st.sidebar.radio("选择主题板块:", list(THEME_MAP.keys()))
real_concept_name = THEME_MAP[selected_theme_label]

st.title(f"🚀 板块透视：{selected_theme_label}")

# 1. 获取全量数据
with st.spinner(f"正在从交易所抓取【{real_concept_name}】数据..."):
    df_all = get_concept_stocks(real_concept_name)

if not df_all.empty:
    count_total = len(df_all)
    
    # 2. 过滤器
    st.sidebar.markdown("---")
    st.sidebar.subheader("🔍 过滤器")
    min_mkt_cap = st.sidebar.slider("最小市值 (亿)", 0, 1000, 50) 
    
    # 过滤与排序
    if df_all['mkt_cap'].sum() == 0:
        st.sidebar.warning("⚠️ 警告：数据源未返回市值，已显示全部股票。")
        df_filtered = df_all
    else:
        df_filtered = df_all[df_all['mkt_cap'] > (min_mkt_cap * 100000000)].copy()
    
    df_filtered = df_filtered.sort_values(by='pct_chg', ascending=False)
    
    st.markdown(f"* 共抓取 **{count_total}** 只，过滤后剩余 **{len(df_filtered)}** 只。")
    
    # 3. 概览表格
    st.dataframe(
        df_filtered,
        column_config={
            "code": "代码", "name": "名称",
            "price": st.column_config.NumberColumn("现价", format="¥%.2f"),
            "pct_chg": st.column_config.NumberColumn("涨跌幅", format="%.2f%%"),
            "mkt_cap": st.column_config.NumberColumn("总市值", format="¥%.0f"),
            "volume": st.column_config.NumberColumn("成交量"),
        },
        height=300, hide_index=True, use_container_width=True
    )
    
    st.markdown("---")
    
    # 4. 个股详细分析
    st.subheader("💡 智能操盘分析")
    
    if len(df_filtered) > 0:
        stock_options = [f"{row['code']} | {row['name']}" for _, row in df_filtered.iterrows()]
        selected_stock = st.selectbox("选择一只股票查看策略:", stock_options)
        
        if selected_stock:
            code = selected_stock.split(" | ")[0]
            name = selected_stock.split(" | ")[1]
            stock_info = df_filtered[df_filtered['code'] == code].iloc[0]
            curr_price = stock_info['price']
            
            with st.spinner(f"正在分析 {name} ..."):
                hist_df = get_hist_data(code)
            
            if not hist_df.empty:
                plan = generate_trading_plan(hist_df, curr_price)
                
                if plan:
                    # 显示建议卡片
                    c1, c2, c3 = st.columns(3)
                    c1.metric(f"{name}", f"¥{curr_price}", f"{stock_info['pct_chg']}%")
                    
                    status = "⚪ 观望"
                    if curr_price < plan['buy_entry'] * 1.01: status = "🟢 机会区域"
                    elif curr_price > plan['take_profit'] * 0.99: status = "🔴 风险区域"
                    
                    c2.metric("当前状态", status)
                    c3.metric("趋势", plan['trend'])

                    k1, k2, k3 = st.columns(3)
                    k1.success(f"低吸建议: ¥{plan['buy_entry']:.2f}")
                    k2.warning(f"止盈建议: ¥{plan['take_profit']:.2f}")
                    k3.error(f"止损红线: ¥{plan['stop_loss']:.2f}")
                    
                    # --- 修复后的绘图代码 ---
                    fig = go.Figure()
                    
                    # K线图
                    fig.add_trace(go.Candlestick(x=hist_df.index,
                                    open=hist_df['open'], high=hist_df['high'],
                                    low=hist_df['low'], close=hist_df['close'], name='K线'))
                    
                    # 关键修改：使用 plan['upper_hist'] (序列) 而不是 Scalar
                    fig.add_trace(go.Scatter(x=hist_df.index, y=plan['upper_hist'], 
                                             line=dict(color='rgba(200,0,0,0.3)', width=1), name='压力轨'))
                    
                    fig.add_trace(go.Scatter(x=hist_df.index, y=plan['lower_hist'], 
                                             line=dict(color='rgba(0,200,0,0.3)', width=1), name='支撑轨'))
                    
                    fig.add_trace(go.Scatter(x=hist_df.index, y=plan['ma20_hist'], 
                                             line=dict(color='orange', width=1.5), name='MA20'))
                    
                    # 建议点位虚线 (水平线)
                    fig.add_hline(y=plan['buy_entry'], line_dash="dash", line_color="green", annotation_text="建议买入")
                    fig.add_hline(y=plan['take_profit'], line_dash="dash", line_color="red", annotation_text="建议止盈")
                    
                    fig.update_layout(xaxis_rangeslider_visible=False, height=500, title=f"{name} 布林带交易策略")
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.warning("数据不足，无法生成策略。")
            else:
                st.warning("获取历史数据失败。")
    else:
        st.info("无符合条件的股票。")
else:
    st.error("板块数据获取失败，请稍后重试。")
