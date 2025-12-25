import streamlit as st
import akshare as ak
import pandas as pd
import numpy as np
import time
import datetime

# --- 页面配置 ---
st.set_page_config(layout="wide", page_title="AI 实盘指挥部", page_icon="💥")

# --- CSS 暴力美学：只看红绿 ---
st.markdown("""
<style>
    .big-font { font-size: 24px !important; font-weight: 900; }
    /* 涨跌颜色 */
    .signal-buy { background-color: #d4edda; color: #155724; padding: 5px; border-radius: 4px; font-weight: bold; }
    .signal-sell { background-color: #f8d7da; color: #721c24; padding: 5px; border-radius: 4px; font-weight: bold; }
    .signal-hold { background-color: #e2e3e5; color: #383d41; padding: 5px; border-radius: 4px; }
    .signal-stop { background-color: #000; color: #fff; padding: 5px; border-radius: 4px; font-weight: bold; }
</style>
""", unsafe_allow_html=True)

# --- 0. 核心配置 ---
# 默认关注的板块
DEFAULT_SECTOR = "CPO概念" 
# 默认持仓 (方便演示，你可以改)
DEFAULT_PORTFOLIO = "300308, 601138, 002230, 688256"

# --- 1. 数据引擎 (保留最稳健的获取逻辑) ---

@st.cache_data(ttl=600)
def fetch_all_market_caps():
    """市值补全补丁"""
    try:
        df = ak.stock_zh_a_spot_em()
        df = df[['代码', '总市值']].copy()
        df.rename(columns={'代码': 'code', '总市值': 'mkt_cap_patch'}, inplace=True)
        df['mkt_cap_patch'] = pd.to_numeric(df['mkt_cap_patch'], errors='coerce').fillna(0)
        return df
    except: return pd.DataFrame()

@st.cache_data(ttl=300)
def get_sector_stocks(symbol_name):
    """获取板块数据"""
    try:
        df = ak.stock_board_concept_cons_em(symbol=symbol_name)
    except:
        try: df = ak.stock_board_industry_cons_em(symbol=symbol_name)
        except: return pd.DataFrame()
    
    if df.empty: return pd.DataFrame()
    
    # 清洗
    rename_map = {'代码': 'code', '名称': 'name', '最新价': 'price', '涨跌幅': 'pct_chg', '总市值': 'mkt_cap', '成交量': 'volume'}
    df.rename(columns=rename_map, inplace=True)
    
    # 补全字段
    for col in ['code', 'name', 'price', 'pct_chg', 'mkt_cap', 'volume']:
        if col not in df.columns: df[col] = 0
            
    # 数值转换
    for col in ['price', 'pct_chg', 'mkt_cap', 'volume']:
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)

    # 市值修复
    if df['mkt_cap'].sum() == 0:
        patch = fetch_all_market_caps()
        if not patch.empty:
            df = pd.merge(df, patch, on='code', how='left')
            df['mkt_cap'] = df['mkt_cap_patch'].fillna(0)
            
    return df

def get_realtime_price(code):
    """获取单只股票实时行情"""
    try:
        df = ak.stock_zh_a_hist(symbol=code, period="daily", start_date=(datetime.datetime.now()-datetime.timedelta(days=5)).strftime("%Y%m%d"), adjust="qfq")
        if df.empty: return None
        return df.iloc[-1]['收盘']
    except: return None

@st.cache_data(ttl=3600) 
def get_hist_data(code):
    """获取计算指标用的历史数据"""
    end = datetime.datetime.now().strftime("%Y%m%d")
    start = (datetime.datetime.now() - datetime.timedelta(days=120)).strftime("%Y%m%d")
    try:
        df = ak.stock_zh_a_hist(symbol=code, period="daily", start_date=start, end_date=end, adjust="qfq")
        df.rename(columns={'日期': 'date', '开盘': 'open', '收盘': 'close', '最高': 'high', '最低': 'low'}, inplace=True)
        return df
    except: return pd.DataFrame()

# --- 2. 核心量化大脑 (生成指令) ---
def analyze_stock(code, name, current_price=None):
    hist = get_hist_data(code)
    if hist.empty or len(hist) < 20: return None
    
    # 如果没传现价，就用历史最后一天(收盘后)
    if current_price is None:
        current_price = hist.iloc[-1]['close']
        
    # 计算布林带
    hist['MA20'] = hist['close'].rolling(20).mean()
    hist['std'] = hist['close'].rolling(20).std()
    hist['Upper'] = hist['MA20'] + 2*hist['std']
    hist['Lower'] = hist['MA20'] - 2*hist['std']
    
    # 计算ATR
    hist['tr'] = np.maximum((hist['high'] - hist['low']), 
                 np.maximum(abs(hist['high'] - hist['close'].shift(1)), abs(hist['low'] - hist['close'].shift(1))))
    atr = hist['tr'].rolling(14).mean().iloc[-1]
    
    last = hist.iloc[-1]
    
    # === 关键点位 ===
    buy_point = last['Lower'] * 1.01  # 下轨上方1%接货
    sell_point = last['Upper'] * 0.99 # 上轨下方1%出货
    stop_loss = buy_point - 1.5 * atr # 止损
    
    # === 生成指令 ===
    action = "HOLD"
    signal_color = "⚪ 观望"
    suggestion = "多看少动"
    
    # 距离买点差距
    dist_buy = (current_price - buy_point) / current_price
    # 距离卖点差距
    dist_sell = (sell_point - current_price) / current_price
    
    if current_price < stop_loss:
        action = "STOP"
        signal_color = "⚫ 止损"
        suggestion = "破位离场"
    elif current_price <= buy_point * 1.02: # 价格到了买点附近2%以内
        action = "BUY"
        signal_color = "🔴 低吸"
        suggestion = f"挂单 ¥{buy_point:.2f}"
    elif current_price >= sell_point * 0.98: # 价格到了卖点附近2%以内
        action = "SELL"
        signal_color = "🟢 止盈"
        suggestion = f"分批卖出"
    else:
        # 中间状态
        if dist_buy < dist_sell:
            suggestion = f"回踩 ¥{buy_point:.2f} 接"
        else:
            suggestion = f"反弹 ¥{sell_point:.2f} 抛"

    return {
        "代码": code,
        "名称": name,
        "现价": current_price,
        "指令": signal_color,
        "操作建议": suggestion,
        "挂单价(买)": buy_point,
        "止盈价(卖)": sell_point,
        "止损线": stop_loss,
        "action_code": action # 用于排序
    }

# --- 3. 界面逻辑 ---

# 侧边栏：设置区
st.sidebar.header("⚙️ 监控配置")
portfolio_input = st.sidebar.text_area("我的持仓代码 (逗号分隔):", value=DEFAULT_PORTFOLIO, height=100)
sector_select = st.sidebar.selectbox("雷达扫描板块:", ["CPO概念", "人工智能", "芯片概念", "PCB", "低空经济", "机器人概念"])
auto_refresh = st.sidebar.toggle("⚡ 开启 30s 自动循环", value=False)

# 标题
st.title("🛡️ AI 实盘指挥部")
t = datetime.datetime.now().strftime("%H:%M:%S")
if auto_refresh:
    st.caption(f"上次更新: {t} | 状态: 🟢 监控中 (30s刷新)")
else:
    st.caption(f"上次更新: {t} | 状态: ⏸️ 已暂停")

# === 第一部分：我的持仓监控 (最重要，放最上面) ===
st.subheader("💼 我的持仓 · 今日策略")

my_stocks = [x.strip() for x in portfolio_input.split(",") if x.strip()]
my_results = []

if my_stocks:
    cols = st.columns(len(my_stocks))
    for i, code in enumerate(my_stocks):
        # 获取最新数据
        # 这里为了速度，实战中应该用 ak.stock_zh_a_spot_em 批量获取，这里简化逻辑逐个获取保证稳定性
        try:
            # 简单起见，这里假设用户输入的是正确代码
            # 获取名字比较麻烦，这里暂用代码代替或调用一次历史数据拿名字
            df_info = ak.stock_zh_a_spot_em()
            name = df_info[df_info['代码'] == code]['名称'].values[0] if not df_info[df_info['代码'] == code].empty else code
            price = df_info[df_info['代码'] == code]['最新价'].values[0] if not df_info[df_info['代码'] == code].empty else 0
            
            res = analyze_stock(code, name, price)
            if res:
                my_results.append(res)
        except:
            continue

if my_results:
    # 转换成 DataFrame 展示
    df_my = pd.DataFrame(my_results)
    
    # 样式化表格
    st.dataframe(
        df_my[['代码', '名称', '现价', '指令', '操作建议', '挂单价(买)', '止盈价(卖)', '止损线']],
        column_config={
            "现价": st.column_config.NumberColumn(format="¥%.2f"),
            "挂单价(买)": st.column_config.NumberColumn(format="¥%.2f"),
            "止盈价(卖)": st.column_config.NumberColumn(format="¥%.2f"),
            "止损线": st.column_config.NumberColumn(format="¥%.2f"),
        },
        hide_index=True,
        use_container_width=True
    )
else:
    st.info("暂无持仓数据，请在左侧添加代码。")

st.markdown("---")

# === 第二部分：全市场低吸雷达 (只看机会) ===
st.subheader(f"📡 {sector_select} · 低吸机会雷达")

# 获取板块数据
df_sector = get_sector_stocks(sector_select)

if not df_sector.empty:
    # 过滤市值太小的，按成交额排序取前30 (保证速度)
    if 'mkt_cap' in df_sector.columns:
        df_active = df_sector[df_sector['mkt_cap'] > 5000000000].sort_values(by='volume', ascending=False).head(30)
    else:
        df_active = df_sector.head(30)
    
    radar_results = []
    
    # 进度条 (仅非自动模式显示)
    if not auto_refresh:
        progress = st.progress(0)
    
    for i, (idx, row) in enumerate(df_active.iterrows()):
        if not auto_refresh:
            progress.progress((i+1)/len(df_active))
            
        res = analyze_stock(row['code'], row['name'], row['price'])
        
        # 只保留【低吸】信号的股票
        if res and res['action_code'] == "BUY":
            radar_results.append(res)
    
    if not auto_refresh:
        progress.empty()
    
    # 展示雷达结果
    if radar_results:
        st.success(f"🚨 扫描完成！发现 {len(radar_results)} 个潜在买点！")
        df_radar = pd.DataFrame(radar_results)
        
        st.dataframe(
            df_radar[['代码', '名称', '现价', '指令', '操作建议', '挂单价(买)', '止损线']],
            column_config={
                "现价": st.column_config.NumberColumn(format="¥%.2f"),
                "挂单价(买)": st.column_config.NumberColumn(format="¥%.2f"),
                "止损线": st.column_config.NumberColumn(format="¥%.2f"),
            },
            hide_index=True,
            use_container_width=True
        )
    else:
        st.warning(f"🍵 当前板块 ({sector_select}) 龙头股均未出现低吸信号，建议空仓或观望。")

else:
    st.error("板块数据获取失败。")

# --- 自动刷新 ---
if auto_refresh:
    time.sleep(30)
    st.rerun()
