import streamlit as st
import pandas as pd
import akshare as ak
import time

# --- 页面配置 ---
st.set_page_config(
    page_title="游资捕手 v2.0：攻守兼备版",
    page_icon="🦅",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- 核心策略逻辑封装 ---
class YangStrategy:
    
    @staticmethod
    def get_market_data_with_retry(max_retries=3):
        """
        带重试机制的数据获取函数，解决 Timeout 问题
        """
        for i in range(max_retries):
            try:
                # 获取全市场实时行情
                df = ak.stock_zh_a_spot_em()
                
                # 数据清洗
                df = df.rename(columns={
                    '代码': 'Symbol',
                    '名称': 'Name',
                    '最新价': 'Price',
                    '涨跌幅': 'Change_Pct',
                    '换手率': 'Turnover_Rate',
                    '量比': 'Volume_Ratio',
                    '总市值': 'Market_Cap',
                    '最高': 'High',
                    '最低': 'Low',
                    '今开': 'Open'
                })
                
                # 数值转换
                cols = ['Price', 'Change_Pct', 'Turnover_Rate', 'Volume_Ratio', 'Market_Cap', 'High', 'Low', 'Open']
                for col in cols:
                    df[col] = pd.to_numeric(df[col], errors='coerce')
                
                return df
            except Exception as e:
                if i < max_retries - 1:
                    time.sleep(2) # 失败后冷却2秒再试
                    continue
                else:
                    st.toast(f"数据源连接超时，请检查网络或稍后重试: {e}", icon="⚠️")
                    return pd.DataFrame()
        return pd.DataFrame()

    @staticmethod
    def check_sell_signals(holdings_df):
        """
        杨永兴卖出/风控逻辑：
        1. 硬止损：亏损超过阈值（如 -3%）
        2. 冲高回落（止盈）：从当日最高点回撤超过一定幅度（如 3%），说明主力在大卖
        3. 弱势盘整：开盘后一直绿盘
        """
        signals = []
        if holdings_df.empty:
            return signals

        for _, row in holdings_df.iterrows():
            reason = []
            status = "持仓"
            color = "gray"

            # 逻辑A: 硬止损 (当日大跌)
            # 杨永兴纪律：买入后不涨反跌，立即砍仓
            if row['Change_Pct'] < -3.0:
                status = "🛑 止损卖出"
                reason.append("触及 -3% 硬止损线")
                color = "red"
            
            # 逻辑B: 冲高回落 (主力出货)
            # 计算回撤：(最高价 - 现价) / 最高价
            elif row['High'] > 0:
                drawdown = (row['High'] - row['Price']) / row['High'] * 100
                if row['Change_Pct'] > 0 and drawdown > 4.0:
                    status = "💰 止盈撤退"
                    reason.append(f"高点回撤 {drawdown:.1f}%，主力可能在出货")
                    color = "orange"
                elif row['Change_Pct'] < 0 and row['Open'] > row['Price']:
                    # 低开低走或高开低走
                    status = "⚠️ 弱势预警"
                    reason.append("日内承压，甚至低于开盘价")
                    color = "yellow"
            
            signals.append({
                "代码": row['Symbol'],
                "名称": row['Name'],
                "现价": row['Price'],
                "涨跌幅": f"{row['Change_Pct']}%",
                "建议操作": status,
                "原因": "; ".join(reason) if reason else "趋势正常",
                "Color": color
            })
        
        return pd.DataFrame(signals)

    @staticmethod
    def filter_stocks(df, max_cap, min_turnover, min_change, max_change, min_vol_ratio):
        """选股逻辑（保持不变）"""
        if df.empty: return df
        df['Market_Cap_Billions'] = df['Market_Cap'] / 100000000
        filtered = df[
            (df['Market_Cap_Billions'] <= max_cap) &
            (df['Turnover_Rate'] >= min_turnover) &
            (df['Change_Pct'] >= min_change) & 
            (df['Change_Pct'] <= max_change) &
            (df['Volume_Ratio'] >= min_vol_ratio)
        ]
        return filtered.sort_values(by='Turnover_Rate', ascending=False)

# --- UI 界面构建 ---

st.title("🦅 游资捕手 v2.0：攻守兼备版")

# 侧边栏：参数与持仓
with st.sidebar:
    st.header("⚙️ 1. 选股雷达 (买入)")
    max_cap = st.slider("最大市值 (亿)", 50, 500, 200)
    min_turnover = st.slider("最低换手 (%)", 1.0, 15.0, 5.0)
    col_s1, col_s2 = st.columns(2)
    min_change = col_s1.number_input("涨幅下限 (%)", 2.0)
    max_change = col_s2.number_input("涨幅上限 (%)", 8.0)
    min_vol_ratio = st.number_input("最低量比", 1.5)

    st.divider()
    
    st.header("🛡️ 2. 持仓监控 (卖出)")
    st.caption("输入代码(逗号分隔)检测卖出信号")
    user_holdings = st.text_area("持仓代码", value="600519,000001", height=70)
    
    st.divider()
    if st.button("🚀 刷新全市场数据", type="primary"):
        st.cache_data.clear()

# --- 主逻辑 ---

# 1. 获取数据 (增加重试Loading效果)
status_placeholder = st.empty()
status_placeholder.info("⏳ 正在连接交易所接口，下载全市场数据...")

raw_df = YangStrategy.get_market_data_with_retry()

if not raw_df.empty:
    status_placeholder.success(f"✅ 数据更新成功! 扫描股票: {len(raw_df)} 只")
    
    # ----------------------
    # 模块一：持仓风控 (卖出信号)
    # ----------------------
    st.subheader("🛡️ 持仓风控雷达 (Sell Signals)")
    
    holding_codes = [code.strip() for code in user_holdings.split(',') if code.strip()]
    if holding_codes:
        # 从全市场数据中筛选出持仓股
        my_stocks = raw_df[raw_df['Symbol'].isin(holding_codes)]
        
        if not my_stocks.empty:
            sell_signals = YangStrategy.check_sell_signals(my_stocks)
            
            # 使用列布局展示卡片式信号
            cols = st.columns(len(sell_signals))
            for index, row in sell_signals.iterrows():
                # 动态计算展示颜色
                bg_color = "green" if "正常" in row['原因'] else ("red" if "止损" in row['建议操作'] else "orange")
                
                with st.container():
                    st.markdown(f"""
                    <div style="border:1px solid #ddd; padding:10px; border-radius:5px; border-left: 5px solid {row['Color']}; margin-bottom:10px;">
                        <strong>{row['名称']} ({row['代码']})</strong><br>
                        现价: ¥{row['现价']} <span style="color:{'red' if float(row['涨跌幅'][:-1])>0 else 'green'}">({row['涨跌幅']})</span><br>
                        <hr style="margin:5px 0;">
                        信号: <b>{row['建议操作']}</b><br>
                        <span style="font-size:0.8em; color:#666">{row['原因']}</span>
                    </div>
                    """, unsafe_allow_html=True)
        else:
            st.warning("未找到持仓股票数据，请检查代码是否正确（如 600xxx, 00xxxx）。")
    else:
        st.info("请在左侧侧边栏输入持仓代码，开启风控监控。")

    st.divider()

    # ----------------------
    # 模块二：选股池 (买入信号)
    # ----------------------
    st.subheader("🦅 游资狙击池 (Buy Signals)")
    
    result_df = YangStrategy.filter_stocks(
        raw_df, max_cap, min_turnover, min_change, max_change, min_vol_ratio
    )
    
    if len(result_df) > 0:
        st.dataframe(
            result_df[['Symbol', 'Name', 'Price', 'Change_Pct', 'Turnover_Rate', 'Volume_Ratio', 'Market_Cap_Billions']],
            column_config={
                "Symbol": "代码", "Name": "名称",
                "Price": st.column_config.NumberColumn("现价", format="¥%.2f"),
                "Change_Pct": st.column_config.NumberColumn("涨幅", format="%.2f%%"),
                "Turnover_Rate": st.column_config.ProgressColumn("换手率", format="%.2f%%", min_value=0, max_value=20),
                "Market_Cap_Billions": st.column_config.NumberColumn("市值(亿)", format="%.1f")
            },
            hide_index=True,
            use_container_width=True
        )
    else:
        st.info("当前无符合杨永兴严格策略的标的，建议等待盘中异动。")

else:
    status_placeholder.error("❌ 数据获取最终失败。请检查：1. 是否开启了VPN（可能导致无法连接国内接口）；2. 网络是否通畅。建议点击左侧按钮重试。")
