import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
import akshare as ak
import tushare as ts
from datetime import datetime, timedelta
import time
import pytz
import warnings
from sklearn.linear_model import LinearRegression
from sklearn.ensemble import RandomForestRegressor
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split
from sklearn.metrics import r2_score, mean_absolute_error
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import json

# 基础配置
warnings.filterwarnings('ignore')
st.set_page_config(
    page_title="A股专业分析平台 | 动态基本面+AI预测",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 全局常量
BEIJING_TZ = pytz.timezone('Asia/Shanghai')
COLOR_SCHEME = {
    "bull": "#FF0000", "bear": "#009900", "primary": "#0066CC",
    "ma5": "#FF9900", "ma10": "#990099", "ma20": "#00CCCC",
    "vwap": "#FF6600", "predict": "#9933FF"
}

# 网络请求重试配置
session = requests.Session()
retry = Retry(total=3, backoff_factor=0.5, status_forcelist=[403, 408, 500, 502, 503, 504])
session.mount("http://", HTTPAdapter(max_retries=retry))
session.mount("https://", HTTPAdapter(max_retries=retry))

# ===================== 1. 核心数据服务层（可独立封装） =====================
class StockDataService:
    """股票数据服务类 - 统一数据获取接口"""
    def __init__(self, tushare_token=""):
        self.tushare_token = tushare_token
        if tushare_token:
            ts.set_token(tushare_token)
            self.ts_pro = ts.pro_api()
        
    @st.cache_data(ttl=300)  # 5分钟缓存
    def get_stock_price_data(_self, stock_code, period="90", adjust="qfq"):
        """获取股票价格数据（支持不同周期/复权方式）"""
        try:
            end_date = datetime.now().strftime("%Y%m%d")
            start_date = (datetime.now() - timedelta(days=int(period))).strftime("%Y%m%d")
            
            df = ak.stock_zh_a_hist(
                symbol=stock_code, period="daily",
                start_date=start_date, end_date=end_date,
                adjust=adjust, timeout=15
            )
            
            if df.empty:
                raise ValueError("无交易数据")
            
            # 标准化字段
            df.rename(columns={
                "日期": "Date", "开盘": "Open", "最高": "High", "最低": "Low",
                "收盘": "Close", "成交量": "Volume", "成交额": "Amount", "涨跌幅": "Pct_Change"
            }, inplace=True)
            df["Date"] = pd.to_datetime(df["Date"]).dt.date
            df = df.sort_values("Date").reset_index(drop=True)
            
            # 计算技术指标
            df = _self._calculate_technical_indicators(df)
            return df, True
        
        except Exception as e:
            st.warning(f"⚠️ 实时数据获取失败：{str(e)[:50]}，使用模拟数据")
            return _self._generate_simulation_data(period), False
    
    @st.cache_data(ttl=3600)  # 1小时缓存
    def get_fundamental_data(_self, stock_code):
        """获取基本面数据（财务+公司概况）"""
        try:
            # 1. 基础信息
            stock_info_df = ak.stock_info_a_code_name()
            stock_name = stock_info_df[stock_info_df['code'] == stock_code]['name'].iloc[0] if not stock_info_df.empty else "未知股票"
            
            # 2. 财务指标
            fina_data = ak.stock_financial_analysis_indicator(stock=stock_code, timeout=10)
            latest_fina = fina_data.iloc[0] if not fina_data.empty else pd.Series()
            
            # 3. 行业分类
            industry_data = ak.stock_industry_sw(stock_code)
            industry = industry_data['industry_name'].iloc[0] if not industry_data.empty else "未知行业"
            
            # 4. 标准化财务指标
            financial_metrics = {
                "营业收入(亿元)": _self._format_metric(latest_fina, "营业总收入", lambda x: round(x/1e8, 2)),
                "营收同比增长": _self._format_metric(latest_fina, "营业总收入同比增长率", lambda x: f"{x:.2f}%"),
                "毛利率(%)": _self._format_metric(latest_fina, "销售毛利率", lambda x: round(x*100, 2)),
                "研发费用率(%)": _self._format_metric(latest_fina, "研发费用率", lambda x: round(x*100, 2)),
                "净利润(亿元)": _self._format_metric(latest_fina, "净利润", lambda x: round(x/1e8, 2)),
                "净利润同比增长": _self._format_metric(latest_fina, "净利润同比增长率", lambda x: f"{x:.2f}%"),
                "资产负债率(%)": _self._format_metric(latest_fina, "资产负债率", lambda x: round(x*100, 2)),
                "市盈率(TTM)": _self._format_metric(latest_fina, "市盈率TTM", lambda x: round(x, 2)),
                "市净率": _self._format_metric(latest_fina, "市净率", lambda x: round(x, 2)),
                "每股收益(EPS)": _self._format_metric(latest_fina, "基本每股收益", lambda x: round(x, 3))
            }
            
            return {
                "basic_info": {"code": stock_code, "name": stock_name, "industry": industry, "update_time": datetime.now().strftime("%Y-%m-%d %H:%M")},
                "financial": financial_metrics,
                "status": "success"
            }
        
        except Exception as e:
            st.warning(f"⚠️ 基本面数据获取失败：{str(e)[:50]}")
            return {
                "basic_info": {"code": stock_code, "name": "未知股票", "industry": "未知行业", "update_time": datetime.now().strftime("%Y-%m-%d %H:%M")},
                "financial": {k: "数据更新中" for k in ["营业收入(亿元)", "营收同比增长", "毛利率(%)", "研发费用率(%)", "净利润(亿元)", "净利润同比增长", "资产负债率(%)", "市盈率(TTM)", "市净率", "每股收益(EPS)"]},
                "status": "failed"
            }
    
    @st.cache_data(ttl=3600)
    def get_industry_analysis(_self, stock_code):
        """获取行业对比分析数据"""
        try:
            # 1. 获取股票所属行业
            industry_data = ak.stock_industry_sw(stock_code)
            if industry_data.empty:
                return {"status": "failed", "data": {}}
            
            industry = industry_data['industry_name'].iloc[0]
            industry_code = industry_data['industry_code'].iloc[0]
            
            # 2. 获取同行业股票列表
            same_industry_stocks = ak.stock_industry_sw_cons(industry_code)
            if same_industry_stocks.empty:
                return {"status": "failed", "data": {}}
            
            # 3. 筛选龙头股（市值前5）
            top_stocks = same_industry_stocks.head(5)
            industry_compare = {}
            
            for _, row in top_stocks.iterrows():
                try:
                    code = row['symbol']
                    name = row['name']
                    fina_data = ak.stock_financial_analysis_indicator(stock=code, timeout=5)
                    latest = fina_data.iloc[0] if not fina_data.empty else pd.Series()
                    
                    industry_compare[name] = {
                        "股票代码": code,
                        "毛利率(%)": _self._format_metric(latest, "销售毛利率", lambda x: round(x*100, 2)),
                        "市盈率(TTM)": _self._format_metric(latest, "市盈率TTM", lambda x: round(x, 2)),
                        "营收同比增长": _self._format_metric(latest, "营业总收入同比增长率", lambda x: f"{x:.2f}%"),
                        "总市值(亿元)": round(row['market_cap']/1e8, 2) if 'market_cap' in row else "N/A"
                    }
                except:
                    continue
            
            return {
                "status": "success",
                "industry_name": industry,
                "data": industry_compare
            }
        
        except Exception as e:
            st.warning(f"⚠️ 行业分析数据获取失败：{str(e)[:50]}")
            return {"status": "failed", "industry_name": "未知行业", "data": {}}
    
    def _calculate_technical_indicators(self, df):
        """计算技术指标（MA/VWAP/RSI/MACD等）"""
        df = df.copy()
        # 移动平均线
        df["MA5"] = df["Close"].rolling(window=5).mean()
        df["MA10"] = df["Close"].rolling(window=10).mean()
        df["MA20"] = df["Close"].rolling(window=20).mean()
        
        # VWAP
        df["CumVol"] = df["Volume"].cumsum()
        df["CumVolPrice"] = (df["Close"] * df["Volume"]).cumsum()
        df["VWAP"] = df["CumVolPrice"] / (df["CumVol"] + 1e-8)
        
        # RSI
        delta = df["Close"].diff()
        gain = delta.where(delta > 0, 0)
        loss = -delta.where(delta < 0, 0)
        avg_gain = gain.rolling(window=14).mean()
        avg_loss = loss.rolling(window=14).mean()
        rs = avg_gain / (avg_loss + 1e-8)
        df["RSI"] = 100 - (100 / (1 + rs))
        
        # MACD
        ema12 = df["Close"].ewm(span=12, adjust=False).mean()
        ema26 = df["Close"].ewm(span=26, adjust=False).mean()
        df["MACD"] = ema12 - ema26
        df["MACD_Signal"] = df["MACD"].ewm(span=9, adjust=False).mean()
        
        return df
    
    def _generate_simulation_data(self, period):
        """生成高质量模拟数据"""
        days = int(period)
        dates = pd.date_range(end=datetime.now(), periods=days, freq='D')
        
        # 模拟股价走势（符合A股特征）
        base_price = np.random.uniform(10, 200)
        volatility = np.random.normal(0, base_price*0.02, days).cumsum()
        prices = base_price + volatility
        
        df = pd.DataFrame({
            "Date": dates.date,
            "Open": prices + np.random.uniform(-base_price*0.01, base_price*0.01, days),
            "High": prices + np.random.uniform(0, base_price*0.02, days),
            "Low": prices - np.random.uniform(0, base_price*0.02, days),
            "Close": prices,
            "Volume": np.random.randint(1e6, 1e7, days),
            "Amount": np.random.uniform(1e8, 1e9, days),
            "Pct_Change": np.random.uniform(-10, 10, days)
        })
        
        # A股涨跌停限制
        df["High"] = np.minimum(df["High"], df["Open"] * 1.1)
        df["Low"] = np.maximum(df["Low"], df["Open"] * 0.9)
        
        return self._calculate_technical_indicators(df)
    
    def _format_metric(self, series, col, func):
        """格式化财务指标"""
        if col in series.index and not pd.isna(series[col]):
            return func(series[col])
        return "N/A"

# ===================== 2. AI预测服务层 =====================
class StockAIPredictor:
    """股票AI预测服务"""
    def __init__(self):
        self.models = {
            "linear": LinearRegression(),
            "rf": RandomForestRegressor(n_estimators=100, random_state=42)
        }
    
    def predict(self, df, predict_days=30, model_type="rf"):
        """多模型股价预测"""
        try:
            df_pred = df.copy().dropna()
            if len(df_pred) < 60:
                return None, "数据量不足（需≥60个交易日）"
            
            # 特征工程
            features = ["MA5", "MA10", "MA20", "VWAP", "RSI", "MACD", "MACD_Signal", "Volume"]
            X = df_pred[features].values
            y = np.roll(df_pred["Close"].values, -predict_days)[:-predict_days]
            X = X[:-predict_days]
            
            # 数据标准化
            scaler = StandardScaler()
            X_scaled = scaler.fit_transform(X)
            
            # 划分数据集
            X_train, X_test, y_train, y_test = train_test_split(X_scaled, y, test_size=0.2, random_state=42)
            
            # 训练模型
            model = self.models[model_type]
            model.fit(X_train, y_train)
            
            # 模型评估
            y_pred = model.predict(X_test)
            r2 = r2_score(y_test, y_pred)
            mae = mean_absolute_error(y_test, y_pred)
            
            if r2 < 0.3:
                return None, f"模型精度不足（R²={r2:.2f}），无法可靠预测"
            
            # 预测未来价格
            last_features = scaler.transform(df_pred[features].iloc[-predict_days:].values)
            predicted_prices = model.predict(last_features)
            
            # 构造预测结果
            last_date = df_pred["Date"].iloc[-1]
            predict_dates = [last_date + timedelta(days=i) for i in range(1, predict_days+1)]
            
            result = pd.DataFrame({
                "Date": predict_dates,
                "Predicted_Close": predicted_prices,
                "Upper_Bound": predicted_prices * (1 + mae/predicted_prices.mean()),
                "Lower_Bound": predicted_prices * (1 - mae/predicted_prices.mean())
            })
            
            # 生成预测结论
            price_change = (predicted_prices[-1] - df_pred["Close"].iloc[-1]) / df_pred["Close"].iloc[-1]
            if price_change > 0.08:
                conclusion = f"✅ AI预测未来{predict_days}天股价上涨（涨幅{price_change:.2%}），看涨"
            elif price_change < -0.08:
                conclusion = f"❌ AI预测未来{predict_days}天股价下跌（跌幅{abs(price_change):.2%}），看跌"
            else:
                conclusion = f"ℹ️ AI预测未来{predict_days}天股价震荡（波动{abs(price_change):.2%}），中性"
            
            # 附加模型评估信息
            conclusion += f" | 模型精度R²={r2:.2f} | 平均误差MAE={mae:.2f}元"
            
            return result, conclusion
        
        except Exception as e:
            return None, f"预测失败：{str(e)[:50]}"

# ===================== 3. 页面UI层 =====================
class StockAnalysisUI:
    """页面UI渲染类"""
    def __init__(self, data_service, ai_predictor):
        self.data_service = data_service
        self.ai_predictor = ai_predictor
    
    def render_sidebar(self):
        """渲染侧边栏（股票选择+参数配置）"""
        st.sidebar.title("📊 A股专业分析平台")
        
        # 市场状态提示
        market_status = self._get_market_status()
        st.sidebar.caption(f"🕒 北京时间：{market_status['time']}")
        st.sidebar.caption(f"📈 市场状态：{market_status['status']}")
        st.sidebar.caption(f"🔄 数据更新：{market_status['next_update']}")
        
        st.sidebar.divider()
        
        # 股票代码输入
        stock_code = st.sidebar.text_input(
            "股票代码",
            value="688795",
            placeholder="如：688795/000001/300059",
            help="支持沪深A股所有代码"
        )
        
        # 分析周期选择
        period_options = {"1个月": "30", "3个月": "90", "6个月": "180", "1年": "240", "2年": "480"}
        selected_period = st.sidebar.selectbox("分析周期", list(period_options.keys()), index=1)
        
        # AI预测配置
        predict_days = st.sidebar.slider("AI预测天数", 10, 60, 30, 5)
        model_type = st.sidebar.radio("预测模型", ["线性回归", "随机森林"], index=1)
        
        # 手动刷新
        if st.sidebar.button("🔄 立即刷新数据", type="primary"):
            st.cache_data.clear()
            st.rerun()
        
        return {
            "stock_code": stock_code.strip(),
            "period": period_options[selected_period],
            "predict_days": predict_days,
            "model_type": "linear" if model_type == "线性回归" else "rf"
        }
    
    def render_header(self, df, is_real, stock_code):
        """渲染头部数据卡片"""
        if len(df) == 0:
            return
        
        latest = df.iloc[-1]
        prev_close = df.iloc[-2]["Close"] if len(df) > 1 else latest["Close"]
        price_change = latest["Close"] - prev_close
        change_pct = (price_change / prev_close) * 100 if prev_close != 0 else 0
        
        # 头部卡片
        col1, col2, col3, col4, col5 = st.columns(5)
        
        with col1:
            st.metric(
                label="当前股价",
                value=f"¥{latest['Close']:.2f}",
                delta=f"{price_change:.2f} ({change_pct:.2f}%)",
                delta_color="normal" if price_change >= 0 else "inverse"
            )
        
        with col2:
            st.metric(label="成交量", value=self._format_volume(latest['Volume']))
        
        with col3:
            st.metric(label="VWAP", value=f"¥{latest['VWAP']:.2f}")
        
        with col4:
            rsi = latest['RSI'] if not pd.isna(latest['RSI']) else 50
            st.metric(label="RSI(14)", value=f"{rsi:.1f}")
        
        with col5:
            st.metric(label="数据类型", value="实时数据" if is_real else "模拟数据")
        
        st.divider()
    
    def render_main_content(self, config):
        """渲染主内容区"""
        # 获取核心数据
        df, is_real = self.data_service.get_stock_price_data(config["stock_code"], config["period"])
        fundamental_data = self.data_service.get_fundamental_data(config["stock_code"])
        industry_data = self.data_service.get_industry_analysis(config["stock_code"])
        
        # 渲染头部
        self.render_header(df, is_real, config["stock_code"])
        
        # AI预测
        prediction_result, prediction_conclusion = self.ai_predictor.predict(df, config["predict_days"], config["model_type"])
        
        # 标签页布局
        tab1, tab2, tab3, tab4, tab5 = st.tabs([
            "股价走势", "技术分析", "基本面分析", "行业对比", "AI价格预测"
        ])
        
        with tab1:
            self._render_price_chart(df, config, prediction_result)
        
        with tab2:
            self._render_technical_analysis(df)
        
        with tab3:
            self._render_fundamental_analysis(fundamental_data)
        
        with tab4:
            self._render_industry_analysis(industry_data)
        
        with tab5:
            self._render_ai_prediction(prediction_result, prediction_conclusion, config["predict_days"])
        
        # 页脚
        self._render_footer()
    
    def _render_price_chart(self, df, config, prediction_result):
        """渲染股价走势图"""
        fig = make_subplots(rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.05, row_heights=[0.6, 0.2, 0.2])
        
        # K线图
        fig.add_trace(go.Candlestick(
            x=df["Date"], open=df["Open"], high=df["High"], low=df["Low"], close=df["Close"],
            name="K线", increasing_line_color=COLOR_SCHEME["bull"], decreasing_line_color=COLOR_SCHEME["bear"]
        ), row=1, col=1)
        
        # 均线
        fig.add_trace(go.Scatter(x=df["Date"], y=df["MA5"], name="MA5", line=dict(color=COLOR_SCHEME["ma5"], width=1)), row=1, col=1)
        fig.add_trace(go.Scatter(x=df["Date"], y=df["MA10"], name="MA10", line=dict(color=COLOR_SCHEME["ma10"], width=1)), row=1, col=1)
        fig.add_trace(go.Scatter(x=df["Date"], y=df["MA20"], name="MA20", line=dict(color=COLOR_SCHEME["ma20"], width=1)), row=1, col=1)
        
        # VWAP
        fig.add_trace(go.Scatter(x=df["Date"], y=df["VWAP"], name="VWAP", line=dict(color=COLOR_SCHEME["vwap"], width=2)), row=1, col=1)
        
        # AI预测线
        if prediction_result is not None:
            fig.add_trace(go.Scatter(
                x=prediction_result["Date"], y=prediction_result["Predicted_Close"],
                name="AI预测", line=dict(color=COLOR_SCHEME["predict"], width=2, dash="dash")
            ), row=1, col=1)
            # 预测区间
            fig.add_trace(go.Scatter(
                x=prediction_result["Date"], y=prediction_result["Upper_Bound"],
                name="预测上限", line=dict(color=COLOR_SCHEME["predict"], width=1, dash="dot"), showlegend=False
            ), row=1, col=1)
            fig.add_trace(go.Scatter(
                x=prediction_result["Date"], y=prediction_result["Lower_Bound"],
                name="预测下限", line=dict(color=COLOR_SCHEME["predict"], width=1, dash="dot"),
                fill="tonexty", fillcolor="rgba(153, 51, 255, 0.1)", showlegend=False
            ), row=1, col=1)
        
        # 成交量
        fig.add_trace(go.Bar(
            x=df["Date"], y=df["Volume"]/1e4, name="成交量（万手）",
            marker_color=[COLOR_SCHEME["bull"] if c >= o else COLOR_SCHEME["bear"] for c, o in zip(df["Close"], df["Open"])]
        ), row=2, col=1)
        
        # RSI
        fig.add_trace(go.Scatter(
            x=df["Date"], y=df["RSI"], name="RSI(14)", line=dict(color="#FF3366", width=1)
        ), row=3, col=1)
        fig.add_hline(y=70, line_dash="dash", line_color="red", row=3, col=1)
        fig.add_hline(y=30, line_dash="dash", line_color="green", row=3, col=1)
        
        # 图表样式
        fig.update_layout(
            height=800, title=f"{fundamental_data['basic_info']['name']} ({config['stock_code']}) 股价走势",
            title_x=0.5, legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            plot_bgcolor="white", xaxis_rangeslider_visible=False
        )
        fig.update_xaxes(gridcolor="#EEEEEE", tickformat="%Y-%m-%d")
        fig.update_yaxes(gridcolor="#EEEEEE")
        
        st.plotly_chart(fig, use_container_width=True)
    
    def _render_technical_analysis(self, df):
        """渲染技术分析"""
        st.subheader("📋 技术分析")
        
        if len(df) < 20:
            st.warning("⚠️ 数据量不足，无法生成技术分析")
            return
        
        latest = df.iloc[-1]
        
        # RSI分析
        rsi = latest['RSI'] if not pd.isna(latest['RSI']) else 50
        col1, col2 = st.columns(2)
        
        with col1:
            st.write("### RSI分析")
            if rsi > 70:
                st.warning(f"RSI={rsi:.1f} → 超买区间，短期回调风险高")
            elif rsi < 30:
                st.success(f"RSI={rsi:.1f} → 超卖区间，短期反弹概率大")
            else:
                st.info(f"RSI={rsi:.1f} → 中性区间，无明确信号")
        
        # MACD分析
        with col2:
            st.write("### MACD分析")
            latest_macd = latest['MACD'] if not pd.isna(latest['MACD']) else 0
            latest_signal = latest['MACD_Signal'] if not pd.isna(latest['MACD_Signal']) else 0
            prev_macd = df.iloc[-2]['MACD'] if len(df) > 2 and not pd.isna(df.iloc[-2]['MACD']) else 0
            prev_signal = df.iloc[-2]['MACD_Signal'] if len(df) > 2 and not pd.isna(df.iloc[-2]['MACD_Signal']) else 0
            
            if latest_macd > latest_signal and prev_macd < prev_signal:
                st.success("MACD金叉 → 短期看涨信号")
            elif latest_macd < latest_signal and prev_macd > prev_signal:
                st.warning("MACD死叉 → 短期看跌信号")
            else:
                st.info("MACD无交叉 → 趋势延续")
        
        # 均线分析
        st.write("### 均线分析")
        ma_status = []
        if not pd.isna(latest['MA5']) and not pd.isna(latest['MA10']):
            if latest['Close'] > latest['MA5'] > latest['MA10'] > latest['MA20']:
                ma_status.append("✅ 多头排列（短期强势）")
            elif latest['Close'] < latest['MA5'] < latest['MA10'] < latest['MA20']:
                ma_status.append("❌ 空头排列（短期弱势）")
            else:
                ma_status.append("ℹ️ 均线缠绕（震荡行情）")
        
        if ma_status:
            st.write("\n".join(ma_status))
        else:
            st.info("数据不足，无法分析均线排列")
    
    def _render_fundamental_analysis(self, fundamental_data):
        """渲染基本面分析"""
        st.subheader("🏢 基本面分析")
        
        tab1, tab2 = st.tabs(["公司概况", "财务指标"])
        
        with tab1:
            info = fundamental_data['basic_info']
            col1, col2 = st.columns(2)
            with col1:
                st.write(f"### 基本信息")
                st.write(f"**股票代码**：{info['code']}")
                st.write(f"**股票名称**：{info['name']}")
                st.write(f"**所属行业**：{info['industry']}")
                st.write(f"**数据更新时间**：{info['update_time']}")
            
            with col2:
                st.write("### 投资要点")
                st.write("""
                • 财务数据均为最新披露的季度报告
                • 未显示数据表示公司暂未披露
                • 数据仅供参考，不构成投资建议
                • 建议结合行业周期综合分析
                """)
        
        with tab2:
            financial = fundamental_data['financial']
            cols = st.columns(3)
            metrics = list(financial.keys())
            
            for i, metric in enumerate(metrics):
                with cols[i % 3]:
                    st.metric(label=metric, value=financial[metric])
            
            # 财务健康度分析
            st.write("### 财务健康度分析")
            try:
                # 毛利率分析
                gross_margin = financial['毛利率(%)']
                if gross_margin not in ["N/A", "数据更新中"] and isinstance(gross_margin, (int, float)):
                    if gross_margin > 40:
                        st.success(f"毛利率{gross_margin}% → 高于行业平均，产品竞争力强")
                    elif gross_margin > 20:
                        st.info(f"毛利率{gross_margin}% → 行业中等水平")
                    else:
                        st.warning(f"毛利率{gross_margin}% → 低于行业平均，盈利压力大")
                
                # 市盈率分析
                pe = financial['市盈率(TTM)']
                if pe not in ["N/A", "数据更新中"] and isinstance(pe, (int, float)):
                    if pe < 30:
                        st.success(f"市盈率{pe} → 估值偏低，具备安全边际")
                    elif pe < 80:
                        st.info(f"市盈率{pe} → 估值合理，匹配行业水平")
                    else:
                        st.warning(f"市盈率{pe} → 估值偏高，需警惕回调风险")
            except:
                st.info("数据不足，无法生成财务健康度分析")
    
    def _render_industry_analysis(self, industry_data):
        """渲染行业对比分析"""
        st.subheader("🏭 行业分析")
        
        if industry_data['status'] == "failed" or not industry_data['data']:
            st.warning("⚠️ 无法获取行业数据，暂不支持行业对比")
            return
        
        st.write(f"### 所属行业：{industry_data['industry_name']}")
        
        # 行业龙头对比
        st.write("### 行业龙头对比")
        compare_df = pd.DataFrame.from_dict(industry_data['data'], orient='index')
        st.dataframe(compare_df, use_container_width=True)
        
        # 行业分析结论
        st.write("### 行业分析结论")
        st.write("""
        1. **毛利率对比**：反映公司产品竞争力与行业地位
        2. **市盈率对比**：反映市场对公司成长预期的差异
        3. **营收增长对比**：反映公司发展速度与行业趋势
        4. **投资建议**：优先选择毛利率高、增长快、估值合理的龙头企业
        """)
    
    def _render_ai_prediction(self, prediction_result, conclusion, predict_days):
        """渲染AI预测结果"""
        st.subheader("🤖 AI价格预测")
        
        if prediction_result is None:
            st.warning(f"⚠️ {conclusion}")
            return
        
        st.success(conclusion)
        
        # 预测表格
        st.write(f"### 未来{predict_days}天价格预测")
        st.dataframe(
            prediction_result.round(2),
            use_container_width=True,
            column_config={
                "Date": "预测日期",
                "Predicted_Close": st.column_config.NumberColumn("预测价格（¥）", format="%.2f"),
                "Upper_Bound": st.column_config.NumberColumn("上限（¥）", format="%.2f"),
                "Lower_Bound": st.column_config.NumberColumn("下限（¥）", format="%.2f")
            }
        )
        
        # 风险提示
        st.write("### 🚨 重要提示")
        st.write("""
        • AI预测基于历史数据和技术指标，不考虑突发消息、政策变化等外部因素
        • 预测误差范围：基于模型MAE动态计算，实际价格可能超出预测区间
        • 短期预测（10-30天）参考性较高，长期预测（>60天）仅供参考
        • 市场有风险，投资需谨慎，本预测不构成任何投资建议
        """)
    
    def _render_footer(self):
        """渲染页脚"""
        st.divider()
        st.write("""
        📊 A股专业分析平台 | 数据来源：上交所/深交所/AKShare | 
        ⚠️ 免责声明：本平台数据仅供参考，不构成任何投资建议 |
        🔧 技术支持：Streamlit + Plotly + Scikit-learn
        """)
    
    def _get_market_status(self):
        """获取市场状态"""
        now = datetime.now(BEIJING_TZ)
        today = now.date()
        
        # 交易时间判断
        is_trading_day = now.weekday() < 5
        market_open = datetime.strptime(f"{today} 09:30", "%Y-%m-%d %H:%M").replace(tzinfo=BEIJING_TZ)
        market_close = datetime.strptime(f"{today} 15:00", "%Y-%m-%d %H:%M").replace(tzinfo=BEIJING_TZ)
        noon_close = datetime.strptime(f"{today} 11:30", "%Y-%m-%d %H:%M").replace(tzinfo=BEIJING_TZ)
        noon_open = datetime.strptime(f"{today} 13:00", "%Y-%m-%d %H:%M").replace(tzinfo=BEIJING_TZ)
        
        is_trading = False
        if is_trading_day:
            morning_trade = market_open <= now <= noon_close
            afternoon_trade = noon_open <= now <= market_close
            is_trading = morning_trade or afternoon_trade
        
        # 生成状态信息
        status = "交易中" if is_trading else "休市中"
        next_update = (now + timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S") if is_trading else "下一交易日09:30"
        
        return {
            "time": now.strftime("%Y-%m-%d %H:%M:%S"),
            "status": status,
            "next_update": next_update
        }
    
    def _format_volume(self, volume):
        """格式化成交量"""
        if pd.isna(volume):
            return "0手"
        volume_hand = volume / 100
        if volume_hand >= 1e8:
            return f"{volume_hand/1e8:.2f}亿手"
        elif volume_hand >= 1e4:
            return f"{volume_hand/1e4:.2f}万手"
        else:
            return f"{volume_hand:.0f}手"

# ===================== 4. 主程序入口 =====================
def main():
    """主程序"""
    # 初始化服务
    data_service = StockDataService(tushare_token="")  # 填入Tushare Token可提升数据质量
    ai_predictor = StockAIPredictor()
    ui = StockAnalysisUI(data_service, ai_predictor)
    
    # 渲染UI
    config = ui.render_sidebar()
    ui.render_main_content(config)

if __name__ == "__main__":
    main()
