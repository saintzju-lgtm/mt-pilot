import streamlit as st
import pandas as pd
import akshare as ak
import time
import threading
from datetime import datetime

# --- 页面配置 ---
st.set_page_config(
    page_title="游资捕手 v3.3：绝对稳定版",
    page_icon="🦅",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- 核心策略逻辑 ---
class YangStrategy:
    
    @staticmethod
    def get_market_data_silent(max_retries=3):
        """
        绝对静默版数据获取：
        移除所有 print/logging，任何输出都会导致 Streamlit 线程崩溃。
        """
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
                return df, None # Data, Error
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
        df['Buy_Price'] = df['Price']
        df['Stop_Loss'] = df['Price'] * 0.97
        df['Target_Price'] = df['Price'] * 1.08
        
        def generate_t1_strategy(row):
            if row['Change_Pct'] > 9.0:
                return "排板策略: 涨停封死则持有，炸板立即走。"
            else:
                return "隔日策略: 明日开盘若不红盘高开，竞价直接走；若高开则持股待涨。"
        
        df['Action_Plan'] = df.apply(generate_t1_strategy, axis=1)
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
                reason.append("触及-3%止损线，趋势走坏")
                color = "#ffe6e6"; border_color = "red"
            elif row['High'] > 0:
                drawdown = (row['High'] - row['Price']) / row['High'] * 100
                if row['Change_Pct'] > 0 and drawdown > 4.0:
                    status = "💰 止盈/避险"
                    reason.append(f"高点回撤{drawdown:.1f}%，主力疑似出货")
                    color = "#fff5e6"; border_color = "orange"
                elif row['Change_Pct'] < 0 and row['Price'] < row['Open']:
                    status = "⚠️ 弱势预警"
                    reason.append("水下震荡，低于开盘价")
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

# --- 核心架构：后台数据引擎 (v3.3 绝对静默版) ---

class BackgroundEngine:
    """
    普通 Python 类，不继承 Streamlit 任何东西，
    也不调用任何 st.xxx 函数，也不 print，也不 logging。
    """
    def __init__(self):
        self.raw_data = pd.DataFrame()
        self.last_update_time = None
        self.last_error = None # 用变量存储错误，而不是打印出来
        self.lock = threading.Lock()
        self.running = True
        
        # 启动线程
        self.thread = threading.Thread(target=self._worker_loop, daemon=True)
        self.thread.start()
        
    def _worker_loop(self):
        """
        后台线程：彻底哑巴模式
        """
        while self.running:
            try:
                # 获取数据
                new_df, error_msg = YangStrategy.get_market_data_silent()
                
                with self.lock:
                    if not new_df.empty:
                        self.raw_data = new_df
                        self.last_update_time = datetime.now()
                        self.last_error = None # 清除错误
                    elif error_msg:
                        self.last_error = error_msg # 记录错误供前端读取
            except Exception as e:
                with self.lock:
                    self.last_error = f"Loop Crash: {str(e)}"
            
            # 休息60秒
            time.sleep(60)

    def get_data(self):
        with self.lock:
            return self.raw_data.copy(), self.last_update_time, self.last_error

# --- 实例化单例 (使用函数装饰器，更稳定) ---
@st.cache_resource
def get_global_engine():
    return BackgroundEngine()

# 获取全局单例
data_engine = get_global_engine()

# --- UI 界面 ---
st.title("🦅 游资捕手 v3.3：绝对稳定版")

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
    # --- 你的专属持仓列表 ---
    user_holdings = st.text_area(
        "持仓代码 (逗号分隔)", 
        value="603256,603986,002938,688795,001301,002837", 
        height=70
    )
    
    st.divider()
    
    if st.button("🚀 刷新视图", type="primary"):
        st.rerun()
        
    auto_refresh = st.checkbox("页面自动同步 (每60s)", value=False)
    if auto_refresh:
        time.sleep(60)
        st.rerun()

# --- 主程序逻辑 ---

status_placeholder = st.empty()

# 1. 从后台引擎“静默”读取数据
raw_df, last_time, last_error = data_engine.get_data()

# 2. 状态展示逻辑
if not raw_df.empty:
    time_str = last_time.strftime('%H:%M:%S')
    # 如果后台有报错信息（比如超时），在这里显示给前端看，而不是在后台崩溃
    if last_error:
        status_placeholder.warning(f"⚠️ 数据已展示 (缓存时间 {time_str})，但后台最新一次更新遇到问题: {last_error}")
    else:
        status_placeholder.success(f"✅ 数据状态健康 | 后台更新时间: {time_str}")

    tab1, tab2 = st.tabs(["🏹 游资狙击池 (买入机会)", "🛡️ 持仓风控雷达 (卖出信号)"])

    # --- TAB 1: 狙击买入 ---
    with tab1:
        result_df = YangStrategy.filter_stocks(raw_df, max_cap, min_turnover, min_change, max_change, min_vol_ratio)
        
        if len(result_df) > 0:
            st.markdown(f"### 🎯 发现 {len(result_df)} 个潜在爆发标的")
            st.dataframe(
                result_df[[
                    'Symbol', 'Name', 'Price', 'Change_Pct', 
                    'Buy_Price', 'Stop_Loss', 'Target_Price', 'Action_Plan',
                    'Turnover_Rate', 'Volume_Ratio'
                ]],
                column_config={
                    "Symbol": "代码", "Name": "名称",
                    "Price": st.column_config.NumberColumn("现价", format="¥%.2f"),
                    "Change_Pct": st.column_config.NumberColumn("涨幅", format="%.2f%%"),
                    "Buy_Price": st.column_config.NumberColumn("建议买入", format="¥%.2f"),
                    "Stop_Loss": st.column_config.NumberColumn("🛑 止损价", format="¥%.2f"),
                    "Target_Price": st.column_config.NumberColumn("🎯 目标价", format="¥%.2f"),
                    "Action_Plan": st.column_config.TextColumn("📋 后续操盘建议", width="medium"),
                    "Turnover_Rate": st.column_config.ProgressColumn("换手", format="%.1f%%", min_value=0, max_value=20),
                    "Volume_Ratio": st.column_config.NumberColumn("量比", format="%.1f")
                },
                hide_index=True,
                use_container_width=True
            )
        else:
            st.info("当前没有符合【杨永兴战法】的标的。建议休息。")

    # --- TAB 2: 风控卖出 ---
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
                st.warning("未找到持仓数据，请检查代码。")
        else:
            st.info("请在左侧输入持仓代码以开启监控。")

else:
    # 冷启动状态
    if last_error:
        status_placeholder.error(f"❌ 初始化失败: {last_error}。请检查网络后刷新。")
    else:
        status_placeholder.info("⏳ 服务器正在后台拉取首次数据（约需3-5秒），请稍等片刻后手动刷新页面...")
