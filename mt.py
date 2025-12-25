import streamlit as st
import akshare as ak
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import datetime

# --- 页面配置 ---
st.set_page_config(layout="wide", page_title="AI 核心资产操盘手", page_icon="🤖")

# --- 0. 核心配置：AI 赛道优选池 (Hardcoded for Precision) ---
# 为了确保相关性，我们手动维护一份核心 AI 股票列表
# 包括：CPO(算力), 大模型, 半导体, PCB
AI_STOCKS_POOL = {
    "算力/CPO": ["300308", "300502", "601138", "000977", "300394"], # 中际旭创, 新易盛, 工业富联, 浪潮信息, 天孚通信
    "大模型/应用": ["002230", "300418", "601360", "002261", "300002"], # 科大讯飞, 昆仑万维, 三六零, 拓维信息, 神州泰岳
    "半导体/芯片": ["688256", "688041", "603501", "600584", "002371"]  # 寒武纪, 海光信息, 韦尔股份, 长电科技, 北方华创
}

# 扁平化列表用于查询
ALL_AI_CODES = [code for category in AI_STOCKS_POOL.values() for code in category]

# --- 1. 数据获取模块 (修复股价不对的问题) ---

@st.cache_data(ttl=60) # 实时行情缓存 60秒
def get_realtime_prices(code_list):
    """
    获取一篮子股票的实时最新价格
    """
    # 获取全市场实时行情
    df_spot = ak.stock_zh_a_spot_em()
    # 筛选出我们的 AI 股票
    df_ai = df_spot[df_spot['代码'].isin(code_list)].copy()
    
    # 整理格式
    df_ai = df_ai[['代码', '名称', '最新价', '涨跌幅', '成交量', '换手率', '总市值']]
    df_ai.rename(columns={'代码': 'code', '名称': 'name', '最新价': 'price', 
                          '涨跌幅': 'pct_chg', '成交量': 'volume', '总市值': 'mkt_cap'}, inplace=True)
    return df_ai

@st.cache_data(ttl=3600) # 历史K线缓存 1小时
def get_hist_data(code):
    """
    获取个股历史K线，用于计算技术指标和支撑压力位
    """
    end_date = datetime.datetime.now().strftime("%Y%m%d")
    start_date = (datetime.datetime.now() - datetime.timedelta(days=180)).strftime("%Y%m%d")
    
    # 使用前复权 (qfq) 确保技术指标计算准确
    try:
        df = ak.stock_zh_a_hist(symbol=code, period="daily", start_date=start_date, end_date=end_date, adjust="qfq")
        df.rename(columns={'日期': 'date', '开盘': 'open', '收盘': 'close', '最高': 'high', '最低': 'low', '成交量': 'volume'}, inplace=True)
        df['date'] = pd.to_datetime(df['date'])
        df.set_index('date', inplace=True)
        return df
    except:
        return pd.DataFrame()

# --- 2. 核心算法：生成实战建议 ---
def generate_trading_plan(df, current_price):
    """
    根据布林带和波动率，计算具体的买卖点位
    """
    if df.empty:
        return None

    data = df.copy()
    
    # 计算布林带 (20, 2)
    data['MA20'] = data['close'].rolling(window=20).mean()
    data['std'] = data['close'].rolling(window=20).std()
    data['Upper'] = data['MA20'] + (data['std'] * 2)
    data['Lower'] = data['MA20'] - (data['std'] * 2)
    
    # 计算 ATR (波动率)
    data['tr'] = np.maximum((data['high'] - data['low']), 
                            np.maximum(abs(data['high'] - data['close'].shift(1)), 
                                       abs(data['low'] - data['close'].shift(1))))
    atr = data['tr'].rolling(window=14).mean().iloc[-1]
    
    last_row = data.iloc[-1]
    
    # === 策略逻辑 ===
    # 支撑位 (Support): 布林带下轨 或 近20日低点
    support_level = max(last_row['Lower'], data['low'].tail(20).min())
    
    # 压力位 (Resistance): 布林带上轨 或 近20日高点
    resistance_level = min(last_row['Upper'], data['high'].tail(20).max())
    
    # 建议买入价: 支撑位上方一点点 (挂单技巧)
    buy_entry = support_level * 1.01
    
    # 建议止盈价: 压力位下方一点点
    take_profit = resistance_level * 0.99
    
    # 建议止损价: 买入价 - 1.5倍 ATR
    stop_loss = buy_entry - (1.5 * atr)
    
    # 趋势判定
    trend = "震荡"
    if current_price > last_row['MA20']:
        trend = "多头趋势 (MA20上方)"
    else:
        trend = "空头趋势 (MA20下方)"
        
    return {
        "trend": trend,
        "buy_entry": buy_entry,
        "take_profit": take_profit,
        "stop_loss": stop_loss,
        "upper": last_row['Upper'],
        "lower": last_row['Lower'],
        "ma20": last_row['MA20']
    }

# --- 3. 界面逻辑 ---

# 侧边栏：板块选择
st.sidebar.title("🔥 AI 赛道扫描")
sector = st.sidebar.radio("选择细分领域:", list(AI_STOCKS_POOL.keys()))
selected_pool = AI_STOCKS_POOL[sector]

st.title(f"🚀 AI 核心资产分析：{sector}")
st.markdown(f"当前板块共追踪 **{len(selected_pool)}** 只龙头标的，数据实时更新。")

# 获取实时数据
with st.spinner("正在连接交易所实时行情..."):
    realtime_df = get_realtime_prices(selected_pool)

if not realtime_df.empty:
    # 按照涨跌幅排序
    realtime_df = realtime_df.sort_values(by="pct_chg", ascending=False)
    
    # 1. 概览列表
    st.dataframe(
        realtime_df,
        column_config={
            "code": "代码",
            "name": "名称",
            "price": st.column_config.NumberColumn("现价", format="¥%.2f"),
            "pct_chg": st.column_config.NumberColumn("涨跌幅", format="%.2f%%", help="今日实时涨跌"),
            "volume": st.column_config.NumberColumn("成交量(手)"),
            "mkt_cap": st.column_config.NumberColumn("总市值(亿)", format="%.1f")
        },
        hide_index=True,
        use_container_width=True
    )
    
    st.markdown("---")
    
    # 2. 个股深度实战分析
    st.subheader("💡 个股实战决策终端")
    
    # 制作一个选项列表: "代码 | 名称"
    select_options = [f"{row['code']} | {row['name']}" for _, row in realtime_df.iterrows()]
    selected_option = st.selectbox("请选择要分析的股票:", select_options)
    
    if selected_option:
        code = selected_option.split(" | ")[0]
        name = selected_option.split(" | ")[1]
        
        # 获取该股当前实时信息
        current_info = realtime_df[realtime_df['code'] == code].iloc[0]
        curr_price = current_info['price']
        
        # 获取历史计算指标
        hist_df = get_hist_data(code)
        
        if not hist_df.empty:
            plan = generate_trading_plan(hist_df, curr_price)
            
            # --- 核心：实战结论卡片 ---
            st.info(f"📊 **{name} ({code})** 交易计划")
            
            # 第一行：现价与趋势
            c1, c2, c3 = st.columns(3)
            c1.metric("当前价格", f"¥{curr_price}", f"{current_info['pct_chg']}%")
            c2.metric("短期趋势", plan['trend'])
            
            # 计算现价距离买点和卖点的距离
            dist_to_buy = (curr_price - plan['buy_entry']) / curr_price
            
            status_html = ""
            if curr_price < plan['buy_entry'] * 1.02:
                status_html = "<span style='color:red; font-weight:bold'>🎯 价格处于击球区，关注低吸机会！</span>"
            elif curr_price > plan['take_profit'] * 0.98:
                status_html = "<span style='color:green; font-weight:bold'>⚠️ 价格接近压力位，注意风险！</span>"
            else:
                status_html = "<span style='color:grey'>⏳ 价格位于中间区域，建议观望。</span>"
                
            c3.write(f"决策建议: {status_html}", unsafe_allow_html=True)
            
            st.markdown("---")
            
            # 第二行：具体的三个价格点位 (核心功能)
            k1, k2, k3 = st.columns(3)
            
            k1.success(f"💰 建议买入价\n\n# **¥{plan['buy_entry']:.2f}**\n(支撑位附近)")
            k2.warning(f"🚀 建议止盈价\n\n# **¥{plan['take_profit']:.2f}**\n(压力位附近)")
            k3.error(f"🛑 建议止损价\n\n# **¥{plan['stop_loss']:.2f}**\n(破位离场)")
            
            # --- 可视化图表 ---
            st.subheader("技术面详解")
            
            fig = go.Figure()
            
            # K线
            fig.add_trace(go.Candlestick(x=hist_df.index,
                            open=hist_df['open'], high=hist_df['high'],
                            low=hist_df['low'], close=hist_df['close'], name='K线'))
            
            # 布林带
            fig.add_trace(go.Scatter(x=hist_df.index, y=plan['upper'], line=dict(color='gray', width=1, dash='dot'), name='压力轨'))
            fig.add_trace(go.Scatter(x=hist_df.index, y=plan['lower'], line=dict(color='gray', width=1, dash='dot'), name='支撑轨'))
            fig.add_trace(go.Scatter(x=hist_df.index, y=plan['ma20'], line=dict(color='orange', width=1.5), name='趋势线(MA20)'))
            
            # 标记买卖点建议
            fig.add_hline(y=plan['buy_entry'], line_dash="dash", line_color="red", annotation_text="建议买入区域")
            fig.add_hline(y=plan['take_profit'], line_dash="dash", line_color="green", annotation_text="建议止盈区域")
            
            fig.update_layout(xaxis_rangeslider_visible=False, height=500, title="布林带交易通道")
            st.plotly_chart(fig, use_container_width=True)
            
            st.caption(f"注：止损位基于 ATR 波动率计算 ({plan['stop_loss']:.2f})。以上建议仅基于技术指标，不构成投资建议。")

else:
    st.error("无法获取数据，请检查网络连接。")
