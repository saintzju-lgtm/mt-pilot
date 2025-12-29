import streamlit as st
import pandas as pd
import akshare as ak
import time
import threading
import ssl
import random # 引入随机库，用于模拟人类操作
from datetime import datetime, timedelta, timezone

# --- 1. SSL 补丁 ---
try:
    _create_unverified_https_context = ssl._create_unverified_context
except AttributeError:
    pass
else:
    ssl._create_default_https_context = _create_unverified_https_context

# --- 2. 页面配置 ---
st.set_page_config(
    page_title="游资捕手 v5.3：慢速稳定版",
    page_icon="🦅",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- 3. 核心策略逻辑 ---
class YangStrategy:
    
    @staticmethod
    def get_market_data_silent(max_retries=3):
        """全市场粗筛"""
        for i in range(max_retries):
            try:
                df = ak.stock_zh_a_spot_em()
                df = df.rename(columns={
                    '代码': 'Symbol', '名称': 'Name', '最新价': 'Price',
                    '涨跌幅': 'Change_Pct', '换手率': 'Turnover_Rate',
                    '量比': 'Volume_Ratio', '总市值': 'Market_Cap',
                    '最高': 'High', '最低': 'Low', '今开': 'Open',
                    '成交量': 'Volume', '成交额': 'Amount'
                })
                cols = ['Price', 'Change_Pct', 'Turnover_Rate', 'Volume_Ratio', 'Market_Cap', 'High', 'Low', 'Open', 'Volume', 'Amount']
                for col in cols:
                    df[col] = pd.to_numeric(df[col], errors='coerce')
                # 确保代码列是字符串
                df['Symbol'] = df['Symbol'].astype(str)
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
    def deep_scan_stock(symbol, current_price):
        """
        深度体检：大幅增加延迟，解决超时问题
        """
        symbol_str = str(symbol)
        
        # 重试机制
        for attempt in range(3):
            try:
                # --- 核心修复：大幅增加间隔 ---
                # 随机休眠 1.0 到 1.5 秒，模拟人类点击，防止被封 IP
                sleep_time = random.uniform(1.0, 1.5)
                time.sleep(sleep_time)
                
                # 拉取历史数据
                hist_df = ak.stock_zh_a_hist(symbol=symbol_str, period="daily", adjust="qfq")
                
                if hist_df.empty or len(hist_df) < 20:
                    if attempt < 2: continue 
                    return "⚪ 数据不足", "⚪ 数据不足"
                
                # 1. 均线趋势
                close_prices = hist_df['close']
                ma5 = close_prices.rolling(5).mean().iloc[-1]
                ma10 = close_prices.rolling(10).mean().iloc[-1]
                ma20 = close_prices.rolling(20).mean().iloc[-1]
                
                trend_str = "⚪ 震荡/空头"
                # 宽松判断：只要站上5日线且5>10即可
                if current_price > ma5 and ma5 > ma10:
                    if ma10 > ma20:
                        trend_str = "📈 多头排列(优)"
                    else:
                        trend_str = "📈 短线强势"
                elif current_price < ma5:
                    trend_str = "📉 破5日线(弱)"
                
                # 2. 位置风险
                lowest_20 = hist_df['low'].tail(20).min()
                if lowest_20 == 0: lowest_20 = 0.01 
                
                position_ratio = current_price / lowest_20
                
                pos_str = "✅ 底部/腰部"
                if position_ratio > 1.6:
                    pos_str = "⚠️ 高位(慎)" 
                
                return trend_str, pos_str
                
            except Exception as e:
                # 失败后，休息更久再试
                if attempt < 2:
                    time.sleep(2.0 + attempt) 
                    continue
                else:
                    return "⚪ 获取超时", "⚪ 获取超时"
        
        return "⚪ 未知错误", "⚪ 未知错误"

    @staticmethod
    def calculate_battle_plan(df):
        if df.empty: return df
        df['Buy_Price'] = df['Price']
        df['Stop_Loss'] = df['Price'] * 0.97
        df['Target_Price'] = df['Price'] * 1.08
        
        def analyze_morphology(row):
            if row['Price'] == 0: return "数据缺失"
            
            avg_price = 0
            if row['Volume'] > 0:
                avg_price = row['Amount'] / (row['Volume'] * 100)
            
            vwap_status = ""
            if avg_price > 0:
                if row['Price'] > avg_price: vwap_status = "🌊水上"
                else: vwap_status = "🏊水下"

            upper_shadow = 0
            if row['Price'] > 0:
                upper_shadow = (row['High'] - row['Price']) / row['Price']
            
            pre_close = row['Price'] / (1 + row['Change_Pct'] / 100)
            max_change_pct = (row['High'] - pre_close) / pre_close * 100 if pre_close > 0 else 0

            if max_change_pct > 9.5 and row['Change_Pct'] < 9.0:
                return f"💣 炸板 | {vwap_status}"
            
            if upper_shadow < 0.005 and row['Change_Pct'] > 3.0:
                return f"🚀 光头强 | {vwap_status}"
            
            if upper_shadow > 0.02:
                return f"⚡ 长上影 | {vwap_status}"
            
            return f"✅ 均势 | {vwap_status}"

        df['Morphology'] = df.apply(analyze_morphology, axis=1)

        def calculate_win_score(row):
            score = 60
            if row['Turnover_Rate'] > 15: score += 15
            elif row['Turnover_Rate'] > 10: score += 10
            
            if row['Volume_Ratio'] > 4.0: score += 10
            elif row['Volume_Ratio'] > 2.5: score += 8
            
            if "水上" in row['Morphology']: score += 10
            
            if "光头强" in row['Morphology']: score += 15
            elif "长上影" in row['Morphology']: score -= 15
            elif "炸板" in row['Morphology']: score -= 30
            
            if 4.0 <= row['Change_Pct'] <= 8.5: score += 5
            
            return min(max(score, 0), 99)

        df['Win_Score'] = df.apply(calculate_win_score, axis=1)
        return df

    @staticmethod
    def check_sell_signals(holdings_df):
        signals = []
        if holdings_df.empty: return pd.DataFrame()

        for _, row in holdings_df.iterrows():
            reason = []
            status = "持仓观察"
            color = "#e6f3ff"; border_color = "#ccc"

            if row['Change_Pct'] < -3.0:
                status = "🛑 止损卖出"; reason.append("触及-3%止损线")
                color = "#ffe6e6"; border_color = "red"
            elif row['High'] > 0:
                drawdown = (row['High'] - row['Price']) / row['High'] * 100
                if row['Change_Pct'] > 0 and drawdown > 4.0:
                    status = "💰 止盈/避险"; reason.append(f"回撤{drawdown:.1f}%")
                    color = "#fff5e6"; border_color = "orange"
                elif row['Change_Pct'] < 0 and row['Price'] < row['Open']:
                    status = "⚠️ 弱势预警"; reason.append("水下震荡")
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
        result = YangStrategy.calculate_battle_plan(filtered)
        return result.sort_values(by='Win_Score', ascending=False)

# --- 4. 后台数据引擎 ---
class BackgroundEngine:
    def __init__(self):
        self.raw_data = pd.DataFrame()
        self.last_update_time = None
        self.last_error = None
        self.error_count = 0 
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
                        self.last_error = None; self.error_count = 0   
                    elif error_msg:
                        self.error_count += 1
                        if self.error_count >= 3: self.last_error = error_msg
            except Exception as e:
                with self.lock:
                    self.error_count += 1
                    if self.error_count >= 3: self.last_error = f"Loop Crash: {str(e)}"
            time.sleep(180) # 3分钟

    def get_data(self):
        with self.lock:
            return self.raw_data.copy(), self.last_update_time, self.last_error

@st.cache_resource
def get_global_engine():
    return BackgroundEngine()

data_engine = get_global_engine()

# --- 5. UI 界面 ---
st.title("🦅 游资捕手 v5.3：慢速稳定版")

with st.sidebar:
    st.header("⚙️ 1. 选股参数 (买)")
    max_cap = st.slider("最大市值 (亿)", 50, 500, 200)
    min_turnover = st.slider("最低换手 (%)", 1.0, 15.0, 5.0)
    col1, col2 = st.columns(2)
    min_change = col1.number_input("涨幅下限", 2.0)
    max_change = col2.number_input("涨幅上限", 8.5)
    min_vol_ratio = st.number_input("最低量比", 1.5)
    
    st.markdown("---")
    top_n = st.slider("🎯 扫描前 N 名", 5, 50, 15)
    
    st.divider()
    st.header("🛡️ 2. 持仓监控 (卖)")
    user_holdings = st.text_area("持仓代码 (逗号分隔)", value="603256,603986,002938,688795,001301,002837", height=70)
    
    st.divider()
    st.caption("后台自动刷新频率：**3分钟/次**")
    if st.button("🚀 立即手动刷新", type="primary"):
        st.rerun()
    if st.checkbox("页面自动同步 (每180s)", value=False):
        time.sleep(180)
        st.rerun()

# --- 6. 主展示逻辑 ---
status_placeholder = st.empty()
raw_df, last_time, last_error = data_engine.get_data()

if not raw_df.empty:
    time_str = last_time.strftime('%H:%M:%S')
    now = datetime.now(timezone(timedelta(hours=8)))
    is_stale = (now - last_time).total_seconds() > 300
    
    if is_stale and last_error:
        status_placeholder.error(f"⚠️ 网络堵塞 | 数据停滞于: {time_str} | 错误: {last_error}")
    elif last_error:
        status_placeholder.warning(f"⚡ 网络波动 (使用缓存 {time_str})，系统正在后台重连...")
    else:
        status_placeholder.success(f"✅ 系统正常运行 | 更新: {time_str} | 深度扫描模块已优化")

    tab1, tab2 = st.tabs(["🏹 游资狙击池 (买入机会)", "🛡️ 持仓风控雷达 (卖出信号)"])

    with tab1:
        full_result = YangStrategy.filter_stocks(raw_df, max_cap, min_turnover, min_change, max_change, min_vol_ratio)
        display_result = full_result.head(top_n).copy()
        
        if len(display_result) > 0:
            st.markdown(f"### 🧬 正在对 Top {len(display_result)} 中的【🚀 光头强】进行深度体检...")
            
            trends = []
            positions = []
            
            progress_bar = st.progress(0)
            
            # --- 深度扫描循环 ---
            target_count = len(display_result)
            for i, (index, row) in enumerate(display_result.iterrows()):
                
                # 只对光头强进行扫描
                if "光头强" in row['Morphology']:
                    t_str, p_str = YangStrategy.deep_scan_stock(row['Symbol'], row['Price'])
                else:
                    t_str, p_str = "⚪ 非重点跳过", "⚪ 跳过"
                
                trends.append(t_str)
                positions.append(p_str)
                progress_bar.progress((i + 1) / target_count)
            
            display_result['Trend_Check'] = trends
            display_result['Pos_Check'] = positions
            progress_bar.empty()
            
            st.success("✅ 扫描完成。")
            
            # --- 修复：重新加入操作说明文案 ---
            st.info("""
            📋 **杨永兴操盘铁律 (战术面板)：**
            * **买入形态**：只看 [🚀 光头强] + [📈 多头排列] 的票。
            * **卖出纪律**：[🎯 建议卖出] 为止盈位；[🛑 止损价] 跌破必跑。
            * **均线说明**：若显示“获取超时”，请稍等片刻再次刷新，服务器正在排队请求。
            """)
            
            st.dataframe(
                display_result[[
                    'Symbol', 'Name', 
                    'Win_Score', 
                    'Morphology',      
                    'Trend_Check',    
                    'Pos_Check',       
                    'Price', 'Change_Pct', 
                    'Buy_Price', 'Target_Price', 'Stop_Loss', 
                    'Turnover_Rate'
                ]],
                column_config={
                    "Symbol": "代码", "Name": "名称",
                    "Win_Score": st.column_config.ProgressColumn("🔥 胜率分", format="%d", min_value=0, max_value=100),
                    "Morphology": st.column_config.TextColumn("📊 分时/形态", width="medium"),
                    "Trend_Check": st.column_config.TextColumn("📈 均线体检", help="光头强标的深度检测"),
                    "Pos_Check": st.column_config.TextColumn("⛰️ 位置风险", help="光头强标的深度检测"),
                    "Price": st.column_config.NumberColumn("现价", format="¥%.2f"),
                    "Change_Pct": st.column_config.NumberColumn("涨幅", format="%.2f%%"),
                    "Buy_Price": st.column_config.NumberColumn("建议买入", format="¥%.2f"),
                    "Target_Price": st.column_config.NumberColumn("🎯 建议卖出", format="¥%.2f"),
                    "Stop_Loss": st.column_config.NumberColumn("🛑 止损价", format="¥%.2f"),
                    "Turnover_Rate": st.column_config.ProgressColumn("换手", format="%.1f%%", min_value=0, max_value=20),
                },
                hide_index=True,
                use_container_width=True
            )
        else:
            st.info("当前无符合标的。")

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
         st.error(f"❌ 首次连接失败: {last_error}")
    else:
        status_placeholder.info("⏳ 正在建立连接 (3-5秒)...")
