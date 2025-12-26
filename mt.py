import streamlit as st
import pandas as pd
import akshare as ak
import time
from datetime import datetime

# --- 页面配置 ---
st.set_page_config(
    page_title="游资捕手：杨永兴策略复刻版",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- 核心策略逻辑封装 ---
class YangStrategy:
    """
    杨永兴策略核心类：
    1. 聚焦热点与流动性 (高换手)
    2. 捕捉启动瞬间 (量比 + 涨幅)
    3. 小盘灵活 (市值控制)
    """
    
    @staticmethod
    @st.cache_data(ttl=60) # 缓存60秒，避免接口请求过于频繁
    def get_market_data():
        """获取A股实时行情数据"""
        try:
            # 使用 akshare 获取东方财富实时行情
            df = ak.stock_zh_a_spot_em()
            
            # 数据清洗与重命名，方便阅读
            df = df.rename(columns={
                '代码': 'Symbol',
                '名称': 'Name',
                '最新价': 'Price',
                '涨跌幅': 'Change_Pct',
                '换手率': 'Turnover_Rate',
                '量比': 'Volume_Ratio',
                '总市值': 'Market_Cap',
                '成交量': 'Volume',
                '最高': 'High',
                '最低': 'Low'
            })
            
            # 转换数值类型
            cols = ['Price', 'Change_Pct', 'Turnover_Rate', 'Volume_Ratio', 'Market_Cap']
            for col in cols:
                df[col] = pd.to_numeric(df[col], errors='coerce')
                
            return df
        except Exception as e:
            st.error(f"数据获取失败，请检查网络或源接口: {e}")
            return pd.DataFrame()

    @staticmethod
    def filter_stocks(df, max_cap, min_turnover, min_change, max_change, min_vol_ratio):
        """执行杨永兴筛选逻辑"""
        if df.empty:
            return df
        
        # 1. 市值过滤 (杨永兴偏好中小盘，便于拉升)
        # 转换单位：Market_Cap 通常单位是元，我们需要转为亿
        df['Market_Cap_Billions'] = df['Market_Cap'] / 100000000
        filtered = df[df['Market_Cap_Billions'] <= max_cap]
        
        # 2. 活跃度过滤 (换手率是灵魂)
        filtered = filtered[filtered['Turnover_Rate'] >= min_turnover]
        
        # 3. 势能过滤 (捕捉主升浪，去除全天趴窝的，也去除已经涨停买不进的)
        filtered = filtered[
            (filtered['Change_Pct'] >= min_change) & 
            (filtered['Change_Pct'] <= max_change)
        ]
        
        # 4. 量能过滤 (量比放大，说明主力介入)
        # 注意：部分新股或异常数据量比可能为空
        filtered = filtered[filtered['Volume_Ratio'] >= min_vol_ratio]
        
        # 5. 排序：按换手率降序，优先展示最活跃的
        return filtered.sort_values(by='Turnover_Rate', ascending=False)

# --- UI 界面构建 ---

# 标题区
st.title("🦅 游资捕手：杨永兴短线策略系统")
st.markdown("""
> **设计理念：** 基于杨永兴“16个月100倍”的核心逻辑——**唯快不破，流动性为王**。
> 本工具旨在通过实时数据清洗，捕捉当前市场中资金关注度最高、具备爆发潜力的中小盘个股。
""")

st.divider()

# 侧边栏：策略参数配置 (PM思维：让用户拥有控制权)
with st.sidebar:
    st.header("⚙️ 策略参数微调")
    
    st.subheader("1. 盘子大小 (市值)")
    max_cap = st.slider("最大市值 (亿元)", 50, 1000, 200, help="杨永兴偏好小盘股，通常200亿以下弹性最好。")
    
    st.subheader("2. 市场热度 (换手率)")
    min_turnover = st.slider("最低换手率 (%)", 1.0, 20.0, 5.0, help="低于5%的股票通常不在短线猎人视野内。")
    
    st.subheader("3. 进攻信号 (涨跌幅)")
    col1, col2 = st.columns(2)
    with col1:
        min_change = st.number_input("最低涨幅 (%)", value=2.5)
    with col2:
        max_change = st.number_input("最高涨幅 (%)", value=8.5, help="避开已经涨停的，在这个区间追入盈亏比最佳。")
        
    st.subheader("4. 爆发力 (量比)")
    min_vol_ratio = st.number_input("最低量比", value=1.5, step=0.1, help="量比>1.5说明今日成交量显著放大。")

    st.markdown("---")
    auto_refresh = st.checkbox("开启自动刷新 (每60秒)", value=False)
    
    if st.button("🚀 立即扫描全市场"):
        st.cache_data.clear() # 清除缓存强制刷新

# 自动刷新逻辑
if auto_refresh:
    time.sleep(60)
    st.rerun()

# --- 主逻辑执行 ---

# 1. 获取数据
with st.spinner('正在连接交易所数据接口，扫描全市场5000+只股票...'):
    raw_df = YangStrategy.get_market_data()

if not raw_df.empty:
    # 2. 市场概览
    st.subheader("📊 实时市场情绪")
    metric_col1, metric_col2, metric_col3 = st.columns(3)
    
    up_count = len(raw_df[raw_df['Change_Pct'] > 0])
    down_count = len(raw_df[raw_df['Change_Pct'] < 0])
    limit_up_count = len(raw_df[raw_df['Change_Pct'] > 9.8]) # 粗略估计涨停
    
    metric_col1.metric("上涨家数", f"{up_count}", delta="多头力量")
    metric_col2.metric("下跌家数", f"{down_count}", delta_color="inverse")
    metric_col3.metric("涨停(>9.8%)", f"{limit_up_count}", "市场极致热度")

    # 3. 执行筛选
    result_df = YangStrategy.filter_stocks(
        raw_df, max_cap, min_turnover, min_change, max_change, min_vol_ratio
    )
    
    # 4. 结果展示
    st.subheader(f"🎯 策略命中目标 ({len(result_df)} 只)")
    
    if len(result_df) > 0:
        # 格式化展示表格
        st.dataframe(
            result_df[['Symbol', 'Name', 'Price', 'Change_Pct', 'Turnover_Rate', 'Volume_Ratio', 'Market_Cap_Billions']],
            column_config={
                "Symbol": "代码",
                "Name": "名称",
                "Price": st.column_config.NumberColumn("现价", format="¥%.2f"),
                "Change_Pct": st.column_config.NumberColumn(
                    "涨跌幅 (%)", 
                    format="%.2f%%",
                    help="当日涨跌幅"
                ),
                "Turnover_Rate": st.column_config.ProgressColumn(
                    "换手率 (%)",
                    format="%.2f%%",
                    min_value=0,
                    max_value=20,
                    help="越高越活跃"
                ),
                "Volume_Ratio": st.column_config.NumberColumn("量比", format="%.2f"),
                "Market_Cap_Billions": st.column_config.NumberColumn("市值 (亿)", format="%.2f"),
            },
            use_container_width=True,
            hide_index=True
        )
        
        # 5. 重点标的详情 (Top 3)
        st.markdown("### 🔥 重点关注 (Top 3)")
        top_picks = result_df.head(3)
        cols = st.columns(3)
        for i, (index, row) in enumerate(top_picks.iterrows()):
            with cols[i]:
                st.info(f"**{row['Name']}** ({row['Symbol']})")
                st.write(f"涨幅: **{row['Change_Pct']}%**")
                st.write(f"换手: **{row['Turnover_Rate']}%**")
                st.write(f"量比: **{row['Volume_Ratio']}**")
                st.caption("符合 '量价齐升' 形态")

    else:
        st.warning("当前没有符合严格策略的标的。建议：1. 降低换手率要求；2. 放宽涨幅区间；3. 等待市场活跃度回升。")
else:
    st.error("无法获取市场数据，请稍后再试。")

# --- 风险提示 ---
st.divider()
st.caption("""
**风险提示与免责声明：**
1. **数据延迟：** 本工具使用开源数据接口，可能存在秒级或分钟级延迟，不作为即时交易依据。
2. **策略局限：** 杨永兴策略属于高风险超短线策略，极其依赖盘感和卖出纪律（止损）。
3. **切勿盲从：** 筛选出的股票仅供复盘研究，不构成投资建议。股市有风险，入市需谨慎。
""")
