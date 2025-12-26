import streamlit as st
import pandas as pd
import akshare as ak
import time
import threading
from datetime import datetime, timedelta, timezone

# --- 页面配置 ---
st.set_page_config(
    page_title="游资捕手 v3.6：精简实战版",
    page_icon="🦅",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- 核心策略逻辑 ---
class YangStrategy:
    
    @staticmethod
    def get_market_data_silent(max_retries=3):
        """绝对静默版数据获取"""
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
                if i < max_retries - 1:
                    time.sleep(2)
                    continue
                else:
                    return pd.DataFrame(), str(e)
        return pd.DataFrame(), "未知错误"

    @staticmethod
    def calculate_battle_plan(df):
        if df.empty: return df
        # 1. 建议买入：现价
        df['Buy_Price'] = df['Price']
        # 2. 止损价：-3%
        df['Stop_Loss'] = df['Price'] * 0.97
        # 3. 建议卖出价 (止盈)：+8%
        df['Target_Price'] = df['Price'] * 1.08
        
        # 风控雷达逻辑
        def assess_risk_for_buyers(row):
            drawdown = 0
            if row['High'] > 0:
                drawdown = (row['High'] - row['Price']) / row['High'] * 100
            
            if row['Change_Pct'] > 9.0:
                return "🔥 强势封板"
            elif drawdown > 4.0:
                return "⚠️ 冲高回落(慎追)"
            elif row['Price'] < row['Open']:
                return "⚠️ 假阴线(需观察)"
            else:
                return "🟢 趋势向上(可击)"

        df['Risk_Advice'] = df.apply(assess_risk_for_buyers, axis=1)
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
        return YangStrategy.calculate_battle_plan(filtered).sort_values(by='Turnover_Rate', ascending=False)

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
st.title("🦅 游资捕手 v3.6：精简实战版")

with st.sidebar:
    st.header("⚙️ 1. 选股参数 (买)")
    max_cap = st.slider("最大市值 (亿)", 50, 500, 200)
    min_turnover = st.slider("最低换手 (%)", 1.0, 15.0, 5.0)
    col1, col2 = st.columns(2)
    min_change = col1.number_input("涨幅下限", 2.0)
    max_change = col2.number_input("涨幅上限", 8.5)
    min_vol_ratio = st.number_input("最低量比", 1.5)
    
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
        status_placeholder.warning(f"⚠️ 数据展示中 (北京时间 {time_str})，后台报错: {last_error}")
    else:
        status_placeholder.success(f"✅ 数据状态健康 | 更新时间: {time_str} (北京时间)")

    tab1, tab2 = st.tabs(["🏹 游资狙击池 (买入机会)", "🛡️ 持仓风控雷达 (卖出信号)"])

    # --- TAB 1: 狙击买入 (已更新) ---
    with tab1:
        result_df = YangStrategy.filter_stocks(raw_df, max_cap, min_turnover, min_change, max_change, min_vol_ratio)
        
        if len(result_df) > 0:
            st.markdown(f"### 🎯 发现 {len(result_df)} 个标的")
            
            # --- 统一展示操作建议 (替代原本表格里的重复列) ---
            st.info("""
            📋 **杨永兴操盘铁律 (通用剧本)：**
            1. **买入后**：若当日封死涨停，则持有；若炸板，立即走人。
            2. **隔日卖出**：明日集合竞价若**不红盘高开**，开盘直接清仓；若高开，则持股待涨至目标价。
            """)
            
            st.dataframe(
                result_df[[
                    'Symbol', 'Name', 'Price', 'Change_Pct', 
                    'Risk_Advice',     # 风控
                    'Buy_Price', 
                    'Target_Price',    # 建议卖出 (新加回来的)
                    'Stop_Loss', 
                    'Turnover_Rate', 'Volume_Ratio'
                ]],
                column_config={
                    "Symbol": "代码", "Name": "名称",
                    "Price": st.column_config.NumberColumn("现价", format="¥%.2f"),
                    "Change_Pct": st.column_config.NumberColumn("涨幅", format="%.2f%%"),
                    
                    "Risk_Advice": st.column_config.TextColumn("⚡ 实时风控", width="medium"),
                    
                    "Buy_Price": st.column_config.NumberColumn("建议买入", format="¥%.2f"),
                    
                    # --- 恢复建议卖出列 ---
                    "Target_Price": st.column_config.NumberColumn(
                        "🎯 建议卖出", 
                        format="¥%.2f",
                        help="短线第一止盈目标位 (+8%)"
                    ),
                    
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
        status_placeholder.error(f"❌ 初始化失败: {last_error}")
    else:
        status_placeholder.info("⏳ 服务器数据加载中，请稍后...")
