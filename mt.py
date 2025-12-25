import streamlit as st
import akshare as ak
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler
import datetime
import time

# --- 页面配置 ---
st.set_page_config(layout="wide", page_title="AI 智能量化大屏", page_icon="⚡")

# --- 辅助函数：技术指标计算 ---
def calculate_factors(df):
    if df.empty or len(df) < 30:
        return None
    
    data = df.copy()
    
    # 1. 趋势因子
    data['MA5'] = data['close'].rolling(window=5).mean()
    data['MA10'] = data['close'].rolling(window=10).mean()
    data['MA20'] = data['close'].rolling(window=20).mean()
    
    # 2. 动量因子 (RSI)
    delta = data['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    data['RSI'] = 100 - (100 / (1 + rs))
    
    # 3. 波动率
    data['Volatility'] = data['close'].rolling(window=20).std()
    
    # 4. 量价关系
    data['Volume_Ratio'] = data['volume'] / data['volume'].rolling(window=5).mean()
    
    # 构建标签：未来 3 天后的收益率 > 1% 则为 1 (看涨)，否则 0
    # shift(-3) 表示看未来3天
    data['Return_3D'] = data['close'].shift(-3) / data['close'] - 1
    data['Target'] = (data['Return_3D'] > 0.01).astype(int)
    
    return data.dropna()

# --- 核心模块：数据获取与模型训练 ---
@st.cache_data(ttl=3600*12) # 缓存12小时，避免反复下载
def run_market_scan(stock_codes):
    all_data = []
    valid_codes = []
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    # 遍历股票池
    for i, code in enumerate(stock_codes):
        # 进度条更新
        progress = (i + 1) / len(stock_codes)
        progress_bar.progress(progress)
        status_text.text(f"正在分析: {code} ({i+1}/{len(stock_codes)})")
        
        try:
            # 获取最近 1 年数据
            end_date = datetime.datetime.now().strftime("%Y%m%d")
            start_date = (datetime.datetime.now() - datetime.timedelta(days=365)).strftime("%Y%m%d")
            
            df = ak.stock_zh_a_hist(symbol=code, period="daily", start_date=start_date, end_date=end_date, adjust="hfq")
            df.rename(columns={'日期': 'date', '开盘': 'open', '收盘': 'close', '最高': 'high', '最低': 'low', '成交量': 'volume'}, inplace=True)
            df['date'] = pd.to_datetime(df['date'])
            df.set_index('date', inplace=True)
            
            processed = calculate_factors(df)
            if processed is not None:
                processed['code'] = code # 标记代码
                all_data.append(processed)
                valid_codes.append(code)
                
        except Exception:
            continue # 跳过获取失败的股票
            
    status_text.text("数据下载完成，正在训练 AI 模型...")
    
    if not all_data:
        return pd.DataFrame(), None

    # 合并所有股票数据进行“全市场训练”
    full_df = pd.concat(all_data)
    
    # 特征列
    features = ['MA5', 'MA10', 'MA20', 'RSI', 'Volatility', 'Volume_Ratio']
    
    # 训练集与预测集分离
    # 拿最后一行作为“今日待预测”，其余作为历史训练
    train_data = full_df.iloc[:-len(valid_codes)] 
    latest_data = full_df.groupby('code').tail(1) # 取每只股票的最后一天
    
    X_train = train_data[features]
    y_train = train_data['Target']
    
    # AI 模型：随机森林
    model = RandomForestClassifier(n_estimators=100, max_depth=5, random_state=42, n_jobs=-1)
    model.fit(X_train, y_train)
    
    # 预测今日
    latest_X = latest_data[features]
    latest_data['AI_Score'] = model.predict_proba(latest_X)[:, 1] # 取“上涨”的概率
    
    # 整理结果表
    result_df = latest_data[['code', 'close', 'RSI', 'AI_Score']].copy()
    result_df.sort_values(by='AI_Score', ascending=False, inplace=True)
    
    progress_bar.empty()
    status_text.empty()
    
    return result_df, model

# --- 界面逻辑 ---
st.title("🤖 Quant-AI: 全市场自动选股系统")
st.markdown("基于 `RandomForest` 多因子模型，自动扫描并计算上涨概率。")

# 1. 侧边栏配置
st.sidebar.header("⚙️ 扫描设置")
index_choice = st.sidebar.selectbox("选择股票池", ["上证50 (速度快)", "沪深300 (速度中)", "自定义Top20"], index=0)

run_btn = st.sidebar.button("🚀 开始 AI 选股", type="primary")

# 初始化 Session State
if 'results' not in st.session_state:
    st.session_state.results = None

# 2. 执行逻辑
if run_btn:
    with st.spinner("正在初始化股票池..."):
        # 获取成分股列表 (为了演示，这里做简化处理)
        if "上证50" in index_choice:
            # 实际上 akshare 获取成分股接口较慢，这里硬编码几个示例或取少量
            # 真实场景建议用 ak.index_stock_cons(symbol="000016")
            # 这里为了演示稳定性，我们手动定义一个包含热门股的列表
            stock_list = ['600519', '601318', '600036', '601012', '600900', '600030', '600887', '600276', '601166', '600009'] 
        elif "自定义" in index_choice:
            stock_list = ['002594', '300750', '000858', '002415', '000333', '601888', '300059']
        else:
            stock_list = ['600519', '000858'] # 默认
            
    # 执行扫描
    results, model = run_market_scan(stock_list)
    st.session_state.results = results
    st.success(f"扫描完成！共分析 {len(results)} 只股票。")

# 3. 结果展示
if st.session_state.results is not None:
    df_res = st.session_state.results
    
    # --- 模块 A: 核心推荐榜单 ---
    st.subheader("🏆 AI 优选 Top 5")
    
    top_picks = df_res.head(5)
    
    # 漂亮的指标卡片
    cols = st.columns(5)
    for i, (idx, row) in enumerate(top_picks.iterrows()):
        with cols[i]:
            st.metric(
                label=row['code'],
                value=f"{row['AI_Score']:.1%}",
                delta="强力推荐" if row['AI_Score'] > 0.6 else "推荐"
            )

    # 交互式表格
    st.markdown("### 📋 详细选股报告")
    
    st.dataframe(
        df_res,
        column_order=("code", "close", "RSI", "AI_Score"),
        column_config={
            "code": "股票代码",
            "close": st.column_config.NumberColumn("最新价", format="¥%.2f"),
            "RSI": st.column_config.NumberColumn("RSI力度", format="%.1f"),
            "AI_Score": st.column_config.ProgressColumn(
                "AI看涨概率",
                help="模型预测未来3天上涨概率",
                format="%.2f",
                min_value=0,
                max_value=1,
            ),
        },
        hide_index=True,
        use_container_width=True
    )
    
    # --- 模块 B: 个股详情透视 ---
    st.markdown("---")
    st.subheader("🔍 个股深度透视")
    selected_code = st.selectbox("选择要查看详情的股票", df_res['code'].tolist())
    
    if selected_code:
        # 重新获取该股详细数据用于绘图
        end_date = datetime.datetime.now().strftime("%Y%m%d")
        start_date = (datetime.datetime.now() - datetime.timedelta(days=180)).strftime("%Y%m%d")
        detail_df = ak.stock_zh_a_hist(symbol=selected_code, period="daily", start_date=start_date, end_date=end_date, adjust="hfq")
        
        detail_df.rename(columns={'日期': 'date', '开盘': 'open', '收盘': 'close', '最高': 'high', '最低': 'low', '成交量': 'volume'}, inplace=True)
        detail_df['date'] = pd.to_datetime(detail_df['date'])
        
        # 绘图
        fig = go.Figure(data=[go.Candlestick(x=detail_df['date'],
                        open=detail_df['open'], high=detail_df['high'],
                        low=detail_df['low'], close=detail_df['close'], name='K线')])
        
        # 加个简单的均线
        ma20 = detail_df['close'].rolling(window=20).mean()
        fig.add_trace(go.Scatter(x=detail_df['date'], y=ma20, line=dict(color='orange', width=1), name='MA20'))
        
        fig.update_layout(title=f"{selected_code} 走势图", xaxis_rangeslider_visible=False, height=500)
        st.plotly_chart(fig, use_container_width=True)

else:
    st.info("👈 请在左侧选择股票池并点击“开始 AI 选股”")
