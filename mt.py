import streamlit as st
import pandas as pd
import akshare as ak
import time
import threading
import logging  # 引入标准日志库，替代 print，防止 Streamlit 线程冲突
from datetime import datetime

# --- 配置日志 ---
# 这样配置后，后台的信息会输出到终端，但不会被 Streamlit 拦截导致报错
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- 页面配置 ---
st.set_page_config(
    page_title="游资捕手 v3.2：专属持仓版",
    page_icon="🦅",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- 核心策略逻辑 ---
class YangStrategy:
    
    @staticmethod
    def get_market_data_silent(max_retries=3):
        """
        静默版数据获取：移除所有 print 和 st.toast，防止线程报错
        """
        for i in range(max_retries):
            try:
                # 获取全市场实时行情
                df = ak.stock_zh_a_spot_em()
                
                # 数据清洗
                df = df.rename(columns={
                    '代码': 'Symbol', '名称': 'Name', '最新价': 'Price',
                    '涨跌幅': 'Change_Pct', '换手率': 'Turnover_Rate',
                    '量比': 'Volume_Ratio', '总市值': 'Market_Cap',
                    '最高': 'High', '最低': 'Low', '今开': 'Open'
                })
                
                # 数值转换
                cols = ['Price', 'Change_Pct', 'Turnover_Rate', 'Volume_Ratio', 'Market_Cap', 'High', 'Low', 'Open']
                for col in cols:
                    df[col] = pd.to_numeric(df[col], errors='coerce')
                
                return df
            except Exception as e:
                # 使用 logging 而不是 print
                logging.error(f"数据获取重试中... 错误: {e}")
                if i < max_retries - 1:
                    time.sleep(2)
                    continue
                else:
                    return pd.DataFrame()
        return pd.DataFrame()

    @staticmethod
    def calculate_battle_plan(df):
        """生成作战计划"""
        if df.empty: return df
        # 建议买入价：现价
        df['Buy_Price'] = df['Price']
        # 止损价：-3%
        df['Stop_Loss'] = df['Price'] * 0.97
        # 目标价：+8%
        df['Target_Price'] = df['Price'] * 1.08
        
        # 生成 T+1 策略文案
        def generate_t1_strategy(row):
            if row['Change_Pct'] > 9.0:
                return "排板策略: 涨停封死则持有，炸板立即走。"
            else:
                return "隔日策略: 明日开盘若不红盘高开，竞价直接走；若高开则持股待涨。"
        
        df['Action_Plan'] = df.apply(generate_t1_strategy, axis=1)
        return df

    @staticmethod
    def check_sell_signals(holdings_df):
        """卖出/风控信号计算"""
        signals = []
        if holdings_df.empty: return pd.DataFrame()

        for _, row in holdings_df.iterrows():
            reason = []
            status = "持仓观察"
            color = "#e6f3ff"
            border_color = "#ccc"

            # 逻辑A: 硬止损
            if row['Change_Pct'] < -3.0:
                status = "🛑 止损卖出"
                reason.append("触及-3%止损线，趋势走坏")
                color = "#ffe6e6"; border_color = "red"
            
            # 逻辑B: 冲高回落
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
        """筛选逻辑"""
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

# --- 核心架构：后台数据引擎 (静默版) ---
@st.cache_resource
class BackgroundMarketEngine:
    def __init__(self):
        self.raw_data = pd.DataFrame()
        self.last_update_time = None
        self.lock = threading.Lock()
        self.running = True
        
        # 启动后台线程
        self.thread = threading.Thread(target=self._worker_loop, daemon=True)
        self.thread.start()
        
    def _worker_loop(self):
        """
        后台线程：绝对不能包含 print() 或 st.xxx()
        """
        while self.running:
            logging.info("后台引擎开始刷新数据...")
            try:
                # 调用静默版获取函数
                new_df = YangStrategy.get_market_data_silent()
                
                if not new_df.empty:
                    with self.lock:
                        self.raw_data = new_df
                        self.last_update_time = datetime.now()
                    logging.info(f"数据刷新成功，共 {len(new_df)} 条")
                else:
                    logging.warning("数据获取为空")
            except Exception as e:
                logging.error(f"后台刷新异常: {e}")
            
            # 休息60秒 (服务器端刷新频率)
            time.sleep(60)

    def get_latest_data(self):
        """前端读取接口"""
        with self.lock:
            return self.raw_data.copy(), self.last_update_time

# 初始化引擎
data_engine = BackgroundMarketEngine()

# --- UI 界面 ---
st.title("🦅 游资捕手 v3.2：专属持仓版")

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
    st.caption("输入代码，逗号分隔，实时监控主力动向")
    # --- 这里更新了你的默认持仓代码 ---
    user_holdings = st.text_area(
        "持仓代码 (逗号分隔)", 
        value="603256,603986,002938,688795,001301,002837", 
        height=70
    )
    
    st.divider()
    
    if st.button("🚀 刷新视图 (读取后台最新)", type="primary"):
        st.rerun()
        
    auto_refresh = st.checkbox("页面自动同步 (每60s)", value=False)
    if auto_refresh:
        time.sleep(60)
        st.rerun()

# --- 主程序逻辑 ---

status_placeholder = st.empty()

# 1. 直接从内存引擎获取数据
raw_df, last_time = data_engine.get_latest_data()

# 2. 处理冷启动
if raw_df.empty:
    status_placeholder.warning("⏳ 服务器启动中，后台正在进行首次数据拉取，请稍等几秒后手动点击刷新...")
else:
    time_str = last_time.strftime('%H:%M:%S')
    status_placeholder.success(f"✅ 数据已就绪 (Server Cache) | 后台最后更新: {time_str}")

    tab1, tab2 = st.tabs(["🏹 游资狙击池 (买入机会)", "🛡️ 持仓风控雷达 (卖出信号)"])

    # --- TAB 1: 狙击买入 ---
    with tab1:
        result_df = YangStrategy.filter_stocks(raw_df, max_cap, min_turnover, min_change, max_change, min_vol_ratio)
        
        if len(result_df) > 0:
            st.markdown(f"### 🎯 发现 {len(result_df)} 个潜在爆发标的")
            st.caption("建议操作：现价买入，严格执行下方生成的止损价。")
            
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
            
            if not result_df.empty:
                best_pick = result_df.iloc[0]
                st.info(f"""
                **🔥 重点关注：{best_pick['Name']} ({best_pick['Symbol']})**
                * **执行纪律：** 现价 **¥{best_pick['Price']}** 买入，若跌破 **¥{best_pick['Stop_Loss']:.2f}** 立即砍仓。
                * **T+1 剧本：** {best_pick['Action_Plan']}
                """)
        else:
            st.warning("当前没有符合【杨永兴战法】的标的。建议休息。")

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
                st.warning("未找到持仓数据，请检查代码格式。")
        else:
            st.info("请在左侧输入持仓代码以开启监控。")
