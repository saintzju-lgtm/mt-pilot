import streamlit as st
import pandas as pd
import akshare as ak
import time
import threading
import ssl
from datetime import datetime, timedelta, timezone

# --- SSL 修复 ---
try:
    _create_unverified_https_context = ssl._create_unverified_context
except AttributeError:
    pass
else:
    ssl._create_default_https_context = _create_unverified_https_context

# --- 页面配置 ---
st.set_page_config(
    page_title="游资捕手 v3.8：胜率精选版",
    page_icon="🦅",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- 核心策略逻辑 ---
class YangStrategy:
    
    @staticmethod
    def get_market_data_silent(max_retries=3):
        for i in range(max_retries):
            try:
                df = ak.stock_zh_a_spot_em()
                df = df.rename(columns={
                    '代码': 'Symbol', '名称': 'Name', '最新价': 'Price',
                    '涨跌幅': 'Change_Pct', '换手率': 'Turnover_Rate',
                    '量比': 'Volume_Ratio', '总市值': 'Market_Cap',
                    '最高': 'High', '最低': 'Low', '今开': 'Open'
                })
                cols = ['Price', 'Change_Pct', 'Turnover_Rate', 'Volume_Ratio', 'Market_Cap', 'High', 'Low', 'Open']
                for col in cols:
                    df[col] = pd.to_numeric(df[col], errors='coerce')
                return df, None
            except Exception as e:
                sleep_time = (i + 1) * 3
                if i < max_retries - 1:
                    time.sleep(sleep_time)
                    continue
                else:
                    return pd.DataFrame(), str(e)
        return pd.DataFrame(), "网络请求最终失败"

    @staticmethod
    def calculate_battle_plan(df):
        if df.empty: return df
        df['Buy_Price'] = df['Price']
        df['Stop_Loss'] = df['Price'] * 0.97
        df['Target_Price'] = df['Price'] * 1.08
        
        # 1. 风控建议
        def assess_risk_for_buyers(row):
            drawdown = 0
            if row['High'] > 0:
                drawdown = (row['High'] - row['Price']) / row['High'] * 100
            
            if row['Change_Pct'] > 9.5: return "🔥 强势封板"
            elif drawdown > 4.0: return "⚠️ 冲高回落(慎追)"
            elif row['Price'] < row['Open']: return "⚠️ 假阴线(需观察)"
            else: return "🟢 趋势向上(可击)"
            
        df['Risk_Advice'] = df.apply(assess_risk_for_buyers, axis=1)

        # 2. 核心算法：杨氏胜率评分 (Yang Score)
        # 这是一个基于“因子完美度”的打分系统，满分 100
        def calculate_win_score(row):
            score = 60 # 基础及格分
            
            # A. 换手率 (权重最高)：越高越好，说明资金在接力
            if row['Turnover_Rate'] > 15: score += 15
            elif row['Turnover_Rate'] > 10: score += 10
            elif row['Turnover_Rate'] > 7: score += 5
            
            # B. 量比 (爆发力)：越大越好
            if row['Volume_Ratio'] > 4.0: score += 10
            elif row['Volume_Ratio'] > 2.5: score += 8
            elif row['Volume_Ratio'] > 1.8: score += 5
            
            # C. 黄金区间 (涨幅)：杨永兴最喜欢 4%-8% 之间的票，刚启动且没涨停
            if 4.0 <= row['Change_Pct'] <= 8.0: score += 10
            elif 2.0 <= row['Change_Pct'] < 4.0: score += 5
            
            # D. 市值偏好：小盘股加分
            mkt_cap_b = row['Market_Cap'] / 100000000
            if mkt_cap_b < 100: score += 5
            
            # E. 扣分项：回撤过大 (钓鱼线)
            drawdown = 0
            if row['High'] > 0:
                drawdown = (row['High'] - row['Price']) / row['High'] * 100
            if drawdown > 3.0: score -= 15 # 形态坏了，大幅扣分
            
            return min(score, 99) # 封顶99

        df['Win_Score'] = df.apply(calculate_win_score, axis=1)
        
        return df

    @staticmethod
    def check_sell_signals(holdings_df):
        signals = []
        if holdings_df.empty: return pd.DataFrame()

        for _, row in holdings_df.iterrows():
            reason = []
            status = "持仓观察"
            color = "#e6f3ff"
            border_color = "#ccc"

            if row['Change_Pct'] < -3.0:
                status = "🛑 止损卖出"
                reason.append("触及-3%止损线")
                color = "#ffe6e6"; border_color = "red"
            elif row['High'] > 0:
                drawdown = (row['High'] - row['Price']) / row['High'] * 100
                if row['Change_Pct'] > 0 and drawdown > 4.0:
                    status = "💰 止盈/避险"
                    reason.append(f"回撤{drawdown:.1f}%，疑似出货")
                    color = "#fff5e6"; border_color = "orange"
                elif row['Change_Pct'] < 0 and row['Price'] < row['Open']:
                    status = "⚠️ 弱势预警"
                    reason.append("水下震荡")
                    color = "#ffffcc"; border_color = "#cccc00"
            
            signals.append({
                "代码": row['Symbol'], "名称": row['Name'], "现价": row['Price'],
                "涨跌幅": f"{row['Change_Pct']}%", "建议操作": status,
                "原因": "; ".join(reason) if reason else "趋势正常",
                "Color": color, "Border": border_color
            })
        return pd.DataFrame(signals)

    @staticmethod
    def filter_stocks(df, max_cap, min_turnover, min_change, max_change, min_vol_ratio):
        if df.empty: return df
        df['Market_Cap_Billions'] = df['Market_Cap'] / 100000000
        filtered = df[
            (df['Market_Cap_Billions'] <= max_cap) &
            (df['Turnover_Rate'] >= min_turnover) &
            (df['Change_Pct'] >= min_change) & 
            (df['Change_Pct'] <= max_change) &
            (df['Volume_Ratio'] >= min_vol_ratio)
        ]
        # 计算完所有数据后，按照分数降序排列
        result = YangStrategy.calculate_battle_plan(filtered)
        return result.sort_values(by='Win_Score', ascending=False)

# --- 后台数据引擎 ---
class BackgroundEngine:
    def __init__(self):
        self.raw_data = pd.DataFrame()
        self.last_update_time = None
        self.last_error = None 
        self.lock = threading.Lock()
        self.running = True
        self.bj_tz = timezone(timedelta(hours=8))
        self.thread = threading.Thread(target=self._worker_loop, daemon=True)
        self.thread.start()
        
    def _worker_loop(self):
        while self.running:
            try:
                new_df, error_msg = YangStrategy.get_market_data_silent()
                with self.lock:
                    if not new_df.empty:
                        self.raw_data = new_df
                        self.last_update_time = datetime.now(self.bj_tz)
                        self.last_error = None
                    elif error_msg:
                        self.last_error = error_msg
            except Exception as e:
                with self.lock:
                    self.last_error = f"Loop Crash: {str(e)}"
            time.sleep(60)

    def get_data(self):
        with self.lock:
            return self.raw_data.copy(), self.last_update_time, self.last_error

@st.cache_resource
def get_global_engine():
    return BackgroundEngine()

data_engine = get_global_engine()

# --- UI 界面 ---
st.title("🦅 游资捕手 v3.8：胜率精选版")

with st.sidebar:
    st.header("⚙️ 1. 选股参数 (买)")
    max_cap = st.slider("最大市值 (亿)", 50, 500, 200)
    min_turnover = st.slider("最低换手 (%)", 1.0, 15.0, 5.0)
    col1, col2 = st.columns(2)
    min_change = col1.number_input("涨幅下限", 2.0)
    max_change = col2.number_input("涨幅上限", 8.5)
    min_vol_ratio = st.number_input("最低量比", 1.5)
    
    st.markdown("---")
    # --- 新增功能：Top N 控制 ---
    top_n = st.slider("🎯 只展示分数前 N 名", 5, 50, 10, help="为了避免眼花缭乱，建议只看前10名分数最高的。")
    
    st.divider()
    st.header("🛡️ 2. 持仓监控 (卖)")
    user_holdings = st.text_area("持仓代码 (逗号分隔)", value="603256,603986,002938,688795,001301,002837", height=70)
    
    st.divider()
    if st.button("🚀 刷新视图", type="primary"):
        st.rerun()
    if st.checkbox("页面自动同步 (每60s)", value=False):
        time.sleep(60)
        st.rerun()

# --- 主展示逻辑 ---
status_placeholder = st.empty()
raw_df, last_time, last_error = data_engine.get_data()

if not raw_df.empty:
    time_str = last_time.strftime('%H:%M:%S')
    if last_error:
        status_placeholder.warning(f"⚠️ 数据展示中 (缓存 {time_str}) | 后台异常: {last_error}")
    else:
        status_placeholder.success(f"✅ 数据健康 | 更新: {time_str} | 已按“胜率评分”智能排序")

    tab1, tab2 = st.tabs(["🏹 游资狙击池 (买入机会)", "🛡️ 持仓风控雷达 (卖出信号)"])

    # --- TAB 1: 狙击买入 (评分精选) ---
    with tab1:
        # 获取全部符合条件的
        full_result = YangStrategy.filter_stocks(raw_df, max_cap, min_turnover, min_change, max_change, min_vol_ratio)
        
        # 截取前 Top N
        display_result = full_result.head(top_n)
        
        if len(display_result) > 0:
            st.markdown(f"### 🏆 综合评分 Top {len(display_result)} (共发现 {len(full_result)} 只)")
            st.caption("注：**“胜率分”** 基于换手率、量比、形态完美度计算。分数越高，符合“杨永兴爆发模型”的概率越大。")
            
            # 通用剧本说明
            st.info("📋 **操盘纪律：** 现价买入 -> 封板持有/炸板走 -> 明日竞价不红盘直接走。")
            
            st.dataframe(
                display_result[[
                    'Symbol', 'Name', 
                    'Win_Score',       # <--- 核心新列：胜率评分
                    'Price', 'Change_Pct', 
                    'Risk_Advice', 
                    'Buy_Price', 'Target_Price', 'Stop_Loss', 
                    'Turnover_Rate', 'Volume_Ratio'
                ]],
                column_config={
                    "Symbol": "代码", "Name": "名称",
                    
                    # --- 胜率评分可视化 ---
                    "Win_Score": st.column_config.ProgressColumn(
                        "🔥 胜率分",
                        help="根据杨永兴因子计算的形态评分 (0-100)",
                        format="%d",
                        min_value=0,
                        max_value=100,
                    ),
                    
                    "Price": st.column_config.NumberColumn("现价", format="¥%.2f"),
                    "Change_Pct": st.column_config.NumberColumn("涨幅", format="%.2f%%"),
                    "Risk_Advice": st.column_config.TextColumn("⚡ 实时风控", width="medium"),
                    "Buy_Price": st.column_config.NumberColumn("建议买入", format="¥%.2f"),
                    "Target_Price": st.column_config.NumberColumn("🎯 建议卖出", format="¥%.2f"),
                    "Stop_Loss": st.column_config.NumberColumn("🛑 止损价", format="¥%.2f"),
                    "Turnover_Rate": st.column_config.ProgressColumn("换手", format="%.1f%%", min_value=0, max_value=20),
                    "Volume_Ratio": st.column_config.NumberColumn("量比", format="%.1f")
                },
                hide_index=True,
                use_container_width=True
            )
        else:
            st.info("当前无符合标的。")

    # --- TAB 2: 持仓风控 ---
    with tab2:
        holding_codes = [c.strip() for c in user_holdings.split(',') if c.strip()]
        if holding_codes:
            my_stocks = raw_df[raw_df['Symbol'].isin(holding_codes)]
            if not my_stocks.empty:
                sell_signals = YangStrategy.check_sell_signals(my_stocks)
                cols = st.columns(3)
                for i, row in sell_signals.iterrows():
                    with cols[i % 3]:
                        st.markdown(f"""
                        <div style="background-color:{row['Color']}; border:1px solid {row['Border']}; padding:15px; border-radius:8px; margin-bottom:10px;">
                            <b>{row['名称']} ({row['代码']})</b><br>
                            现价: {row['现价']} <span style="color:{'red' if '-' not in row['涨跌幅'] else 'green'}">({row['涨跌幅']})</span>
                            <hr style="margin:5px 0">
                            <b>建议: {row['建议操作']}</b><br>
                            <small>{row['原因']}</small>
                        </div>
                        """, unsafe_allow_html=True)
            else:
                st.warning("未找到持仓数据。")
        else:
            st.info("请输入持仓代码。")
else:
    if last_error:
        st.error(f"❌ 数据获取失败: {last_error}。正在自动重试...")
    else:
        status_placeholder.info("⏳ 服务器正在建立连接 (3-5秒)...")
