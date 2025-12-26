import streamlit as st
import pandas as pd
import akshare as ak
import time

# --- 页面配置 ---
st.set_page_config(
    page_title="游资捕手 v2.1：狙击作战版",
    page_icon="🦅",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- 核心策略逻辑封装 ---
class YangStrategy:
    
    @staticmethod
    def get_market_data_with_retry(max_retries=3):
        """带重试机制的数据获取"""
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
                return df
            except Exception as e:
                if i < max_retries - 1:
                    time.sleep(2)
                    continue
                else:
                    st.toast(f"连接超时，请重试: {e}", icon="⚠️")
                    return pd.DataFrame()
        return pd.DataFrame()

    @staticmethod
    def calculate_battle_plan(df):
        """
        生成作战计划：买入区间、止损价、止盈预期、T+1策略
        """
        if df.empty: return df
        
        # 1. 建议买入价：杨永兴风格是势能确立后立刻进，但不能追太高
        # 逻辑：现价即买点，但设定上限为现价+0.5%（防止滑点过大）
        df['Buy_Price'] = df['Price']
        
        # 2. 严格止损价：成本价 - 3%
        df['Stop_Loss'] = df['Price'] * 0.97
        
        # 3. 短线目标价：成本价 + 8% (博弈隔日溢价)
        df['Target_Price'] = df['Price'] * 1.08
        
        # 4. 生成文字版操盘建议
        def generate_t1_strategy(row):
            if row['Change_Pct'] > 9.0:
                return "排板策略: 涨停封死则持有，炸板立即走。"
            else:
                return "隔日策略: 明日开盘若不红盘高开，竞价直接走；若高开则持股待涨。"
        
        df['Action_Plan'] = df.apply(generate_t1_strategy, axis=1)
        return df

    @staticmethod
    def check_sell_signals(holdings_df):
        """持仓风控逻辑 (v2.0功能保留)"""
        signals = []
        if holdings_df.empty: return pd.DataFrame()

        for _, row in holdings_df.iterrows():
            reason = []
            status = "持仓观察"
            color = "#e6f3ff"
            border_color = "#ccc"

            if row['Change_Pct'] < -3.0:
                status = "🛑 止损卖出"
                reason.append("触及-3%止损线，不仅没涨反而大跌")
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
        """选股逻辑"""
        if df.empty: return df
        df['Market_Cap_Billions'] = df['Market_Cap'] / 100000000
        filtered = df[
            (df['Market_Cap_Billions'] <= max_cap) &
            (df['Turnover_Rate'] >= min_turnover) &
            (df['Change_Pct'] >= min_change) & 
            (df['Change_Pct'] <= max_change) &
            (df['Volume_Ratio'] >= min_vol_ratio)
        ]
        # 计算作战计划
        return YangStrategy.calculate_battle_plan(filtered).sort_values(by='Turnover_Rate', ascending=False)

# --- UI 界面 ---
st.title("🦅 游资捕手 v2.1：狙击作战版")

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
    user_holdings = st.text_area("持仓代码 (逗号分隔)", value="000001,600519", height=70)
    
    st.divider()
    if st.button("🚀 启动全市场扫描", type="primary"):
        st.cache_data.clear()

# --- 主程序 ---
status_placeholder = st.empty()
status_placeholder.info("⏳ 连接交易所数据中... (自动重试机制已开启)")

raw_df = YangStrategy.get_market_data_with_retry()

if not raw_df.empty:
    status_placeholder.success(f"✅ 市场扫描完毕 | 股票总数: {len(raw_df)}")

    # Tab 分页：让买和卖的逻辑更清晰
    tab1, tab2 = st.tabs(["🏹 游资狙击池 (买入机会)", "🛡️ 持仓风控雷达 (卖出信号)"])

    # --- TAB 1: 狙击买入 ---
    with tab1:
        result_df = YangStrategy.filter_stocks(raw_df, max_cap, min_turnover, min_change, max_change, min_vol_ratio)
        
        if len(result_df) > 0:
            st.markdown(f"### 🎯 发现 {len(result_df)} 个潜在爆发标的")
            st.caption("建议操作：现价买入，严格执行下方生成的止损价。")
            
            # 核心数据展示
            st.dataframe(
                result_df[[
                    'Symbol', 'Name', 'Price', 'Change_Pct', 
                    'Buy_Price', 'Stop_Loss', 'Target_Price', 'Action_Plan',
                    'Turnover_Rate', 'Volume_Ratio'
                ]],
                column_config={
                    "Symbol": "代码", 
                    "Name": "名称",
                    "Price": st.column_config.NumberColumn("现价", format="¥%.2f"),
                    "Change_Pct": st.column_config.NumberColumn("涨幅", format="%.2f%%"),
                    
                    # 新增核心作战列
                    "Buy_Price": st.column_config.NumberColumn(
                        "建议买入", 
                        help="建议在此价格附近直接挂单扫货",
                        format="¥%.2f"
                    ),
                    "Stop_Loss": st.column_config.NumberColumn(
                        "🛑 止损价", 
                        help="跌破此价格必须无条件止损 (-3%)",
                        format="¥%.2f"
                    ),
                    "Target_Price": st.column_config.NumberColumn(
                        "🎯 目标价", 
                        help="短期第一止盈目标位",
                        format="¥%.2f"
                    ),
                    "Action_Plan": st.column_config.TextColumn(
                        "📋 后续操盘建议",
                        width="medium"
                    ),
                    
                    "Turnover_Rate": st.column_config.ProgressColumn("换手", format="%.1f%%", min_value=0, max_value=20),
                    "Volume_Ratio": st.column_config.NumberColumn("量比", format="%.1f")
                },
                hide_index=True,
                use_container_width=True
            )
            
            # 重点票详细卡片
            if not result_df.empty:
                best_pick = result_df.iloc[0]
                st.info(f"""
                **🔥 重点关注：{best_pick['Name']} ({best_pick['Symbol']})** * **买入逻辑：** 量比 {best_pick['Volume_Ratio']} + 换手 {best_pick['Turnover_Rate']}%，资金攻击意愿最强。
                * **执行纪律：** 现价 **¥{best_pick['Price']}** 买入，若跌破 **¥{best_pick['Stop_Loss']:.2f}** 立即砍仓。
                * **T+1 剧本：** {best_pick['Action_Plan']}
                """)
        else:
            st.warning("当前没有符合【杨永兴战法】的标的。市场可能处于冰点，建议空仓休息。")

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

else:
    status_placeholder.error("❌ 数据获取失败。请检查网络连接（VPN等）或稍后再试。")
