import streamlit as st
import akshare as ak
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
import time
from plyer import notification
import warnings
warnings.filterwarnings("ignore")

# -------------------------- 1. 初始化配置 --------------------------
st.set_page_config(page_title="杨永兴短线选股工具（无Token版）", layout="wide")

# 全局参数
REFRESH_INTERVAL = 60  # 自动刷新间隔（秒）
MARKET_OPEN_TIME = "09:30:00"
MARKET_CLOSE_TIME = "15:00:00"
# 杨永兴核心参数（可在侧边栏调整）
DEFAULT_CONFIG = {
    "circ_mv_min": 50,    # 流通市值下限（亿）
    "circ_mv_max": 200,   # 流通市值上限（亿）
    "turnover_rate_min": 8,  # 当日换手率下限（%）
    "volume_ratio_min": 1.5, # 量比下限
    "profit_stop_5": 0.05,   # 5%止盈
    "profit_stop_8": 0.08,   # 8%止盈
    "loss_stop_3": 0.03,     # 3%止损
    "position_max": 3,       # 最大持仓数
    "position_single_max": 0.5  # 单只仓位上限
}

# -------------------------- 2. 核心工具函数 --------------------------
def is_market_open():
    """判断当前是否为交易时间"""
    now = datetime.now()
    # 交易日判断（简化版：周一到周五，排除节假日，进阶可对接akshare的交易日历）
    if now.weekday() >= 5:  # 周六/周日
        return False
    # 交易时段判断
    open_time = datetime.strptime(MARKET_OPEN_TIME, "%H:%M:%S").replace(year=now.year, month=now.month, day=now.day)
    close_time = datetime.strptime(MARKET_CLOSE_TIME, "%H:%M:%S").replace(year=now.year, month=now.month, day=now.day)
    return open_time <= now <= close_time

def get_stock_basic():
    """获取A股基础信息（无Token，AkShare）"""
    # 获取全市场A股基础数据
    stock_info_df = ak.stock_info_a_code_name()
    # 获取流通市值数据（实时）
    stock_zh_a_spot_df = ak.stock_zh_a_spot_em()  # 东方财富实时行情
    
    # 数据合并：代码+名称+流通市值
    stock_zh_a_spot_df.rename(columns={
        "代码": "code",
        "名称": "name",
        "流通市值": "circ_mv"
    }, inplace=True)
    # 清理流通市值（转数值，单位：亿）
    stock_zh_a_spot_df["circ_mv"] = stock_zh_a_spot_df["circ_mv"].replace("-", 0)
    stock_zh_a_spot_df["circ_mv"] = pd.to_numeric(stock_zh_a_spot_df["circ_mv"], errors="coerce").fillna(0)
    
    # 剔除ST股、涨跌停股、停牌股
    stock_zh_a_spot_df = stock_zh_a_spot_df[~stock_zh_a_spot_df["name"].str.contains("ST", na=False)]
    stock_zh_a_spot_df = stock_zh_a_spot_df[stock_zh_a_spot_df["涨跌幅"] != "-"]  # 剔除停牌
    stock_zh_a_spot_df = stock_zh_a_spot_df[stock_zh_a_spot_df["涨跌幅"] < 10]   # 剔除涨停
    stock_zh_a_spot_df = stock_zh_a_spot_df[stock_zh_a_spot_df["涨跌幅"] > -10]  # 剔除跌停
    
    # 保留核心列
    basic_df = stock_zh_a_spot_df[["code", "name", "circ_mv"]].copy()
    return basic_df

def get_stock_tech_data(code, trade_days=3):
    """获取单只股票技术指标（均线、换手率、量比）"""
    try:
        # 1. 获取日线数据（近30天，用于计算均线/换手率）
        stock_zh_a_hist_df = ak.stock_zh_a_hist(
            symbol=code,
            period="daily",
            start_date=(datetime.now() - timedelta(days=30)).strftime("%Y%m%d"),
            end_date=datetime.now().strftime("%Y%m%d"),
            adjust="qfq"  # 前复权
        )
        if len(stock_zh_a_hist_df) < trade_days + 20:  # 至少需要3+20天数据计算均线
            return None
        
        # 排序（升序）
        stock_zh_a_hist_df = stock_zh_a_hist_df.sort_values("日期").reset_index(drop=True)
        latest = stock_zh_a_hist_df.iloc[-1]
        
        # 2. 计算均线（5/10/20日）
        stock_zh_a_hist_df["ma5"] = stock_zh_a_hist_df["收盘"].rolling(window=5).mean()
        stock_zh_a_hist_df["ma10"] = stock_zh_a_hist_df["收盘"].rolling(window=10).mean()
        stock_zh_a_hist_df["ma20"] = stock_zh_a_hist_df["收盘"].rolling(window=20).mean()
        
        # 3. 均线多头排列判断
        ma5_gt_ma10 = latest["ma5"] > latest["ma10"]
        ma10_gt_ma20 = latest["ma10"] > latest["ma20"]
        ma5_up = latest["ma5"] > stock_zh_a_hist_df.iloc[-2]["ma5"]
        ma10_up = latest["ma10"] > stock_zh_a_hist_df.iloc[-2]["ma10"]
        ma20_up = latest["ma20"] > stock_zh_a_hist_df.iloc[-2]["ma20"]
        ma_multi_head = ma5_gt_ma10 and ma10_gt_ma20 and ma5_up and ma10_up and ma20_up
        
        # 4. 换手率（近3日递增 + 当日>8%）
        turnover_list = stock_zh_a_hist_df.iloc[-trade_days:]["换手率"].tolist()
        turnover_list = [float(x.replace("%", "")) if isinstance(x, str) else x for x in turnover_list]
        turnover_increase = all(turnover_list[i] < turnover_list[i+1] for i in range(len(turnover_list)-1))
        latest_turnover = float(latest["换手率"].replace("%", "")) if isinstance(latest["换手率"], str) else latest["换手率"]
        
        # 5. 近3日涨幅
        latest_3_close = stock_zh_a_hist_df.iloc[-trade_days:]["收盘"].tolist()
        latest_3_return = (latest_3_close[-1] - latest_3_close[0]) / latest_3_close[0] * 100
        
        # 6. 量比（当日成交量/近5日均量）
        if len(stock_zh_a_hist_df) >= 5:
            avg_vol = stock_zh_a_hist_df.iloc[-6:-1]["成交量"].mean()
            latest_vol = latest["成交量"]
            volume_ratio = latest_vol / avg_vol if avg_vol != 0 else 0
        else:
            volume_ratio = 0
        
        # 7. 5日均线偏离度（买入信号核心）
        ma5_deviation = (latest["收盘"] - latest["ma5"]) / latest["ma5"] * 100
        
        return {
            "code": code,
            "turnover_rate": latest_turnover,
            "turnover_increase": turnover_increase,
            "volume_ratio": volume_ratio,
            "latest_3_return": latest_3_return,
            "ma_multi_head": ma_multi_head,
            "ma5_deviation": ma5_deviation,
            "close": latest["收盘"],
            "ma5": latest["ma5"],
            "take_profit_5": latest["收盘"] * (1 + DEFAULT_CONFIG["profit_stop_5"]),
            "take_profit_8": latest["收盘"] * (1 + DEFAULT_CONFIG["profit_stop_8"]),
            "stop_loss_3": latest["收盘"] * (1 - DEFAULT_CONFIG["loss_stop_3"])
        }
    except Exception as e:
        return None

def select_stocks():
    """核心选股逻辑（无Token）"""
    basic_df = get_stock_basic()
    # 筛选流通市值50-200亿
    basic_df = basic_df[(basic_df["circ_mv"] >= DEFAULT_CONFIG["circ_mv_min"]) & 
                        (basic_df["circ_mv"] <= DEFAULT_CONFIG["circ_mv_max"])]
    if len(basic_df) == 0:
        return pd.DataFrame()
    
    stock_data = []
    total = len(basic_df)
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    for idx, row in basic_df.iterrows():
        status_text.text(f"筛选中：{idx+1}/{total} ({row['name']})")
        tech_data = get_stock_tech_data(row["code"])
        if tech_data:
            stock_info = {
                "股票代码": row["code"],
                "股票名称": row["name"],
                "流通市值(亿)": row["circ_mv"],
                **tech_data
            }
            stock_data.append(stock_info)
        progress_bar.progress((idx+1)/total)
    
    # 筛选核心条件
    if not stock_data:
        progress_bar.empty()
        status_text.empty()
        return pd.DataFrame()
    
    df = pd.DataFrame(stock_data)
    filter_condition = (
        (df["turnover_rate"] > DEFAULT_CONFIG["turnover_rate_min"]) &
        (df["turnover_increase"] == True) &
        (df["volume_ratio"] > DEFAULT_CONFIG["volume_ratio_min"]) &
        (df["latest_3_return"] > 0) &
        (df["latest_3_return"] < 10) &
        (df["ma_multi_head"] == True)
    )
    final_df = df[filter_condition].reset_index(drop=True)
    
    # 标记买入信号 + 仓位建议
    final_df["买入信号"] = final_df["ma5_deviation"].abs() < 2
    final_df["建议仓位(%)"] = np.minimum(100/DEFAULT_CONFIG["position_max"], DEFAULT_CONFIG["position_single_max"]*100)
    final_df["建议仓位(%)"] = final_df["建议仓位(%)"].round(1)
    
    # 重命名列
    final_df.rename(columns={
        "turnover_rate": "当日换手率(%)",
        "volume_ratio": "量比",
        "latest_3_return": "近3日涨幅(%)",
        "ma5_deviation": "5日均线偏离度(%)",
        "close": "当前价格",
        "ma5": "5日均线",
        "take_profit_5": "5%止盈价",
        "take_profit_8": "8%止盈价",
        "stop_loss_3": "3%止损价"
    }, inplace=True)
    
    progress_bar.empty()
    status_text.empty()
    return final_df

def send_notification(title, message):
    """桌面预警通知（扩展功能1：预警）"""
    try:
        notification.notify(
            title=title,
            message=message,
            timeout=10  # 通知显示10秒
        )
    except:
        st.warning("桌面通知功能暂不支持当前系统")

def backtest_simple(code):
    """简单历史回测（扩展功能2：回测）"""
    try:
        # 获取近60天日线数据
        hist_df = ak.stock_zh_a_hist(
            symbol=code,
            period="daily",
            start_date=(datetime.now() - timedelta(days=60)).strftime("%Y%m%d"),
            end_date=datetime.now().strftime("%Y%m%d"),
            adjust="qfq"
        )
        if len(hist_df) < 30:
            return None
        
        # 模拟杨永兴策略回测
        hist_df["ma5"] = hist_df["收盘"].rolling(window=5).mean()
        hist_df["买入信号"] = (hist_df["收盘"] - hist_df["ma5"]).abs() / hist_df["ma5"] < 0.02
        hist_df["止盈5%"] = hist_df["收盘"] * 1.05
        hist_df["止损3%"] = hist_df["收盘"] * 0.97
        
        # 计算累计收益
        hist_df["策略收益"] = 0.0
        hold = False
        buy_price = 0
        for i in range(1, len(hist_df)):
            if not hold and hist_df.iloc[i-1]["买入信号"]:
                buy_price = hist_df.iloc[i]["开盘"]
                hold = True
            elif hold:
                current_price = hist_df.iloc[i]["收盘"]
                if current_price >= buy_price * 1.05 or current_price <= buy_price * 0.97:
                    hist_df.loc[hist_df.index[i], "策略收益"] = (current_price - buy_price) / buy_price * 100
                    hold = False
        
        total_profit = hist_df["策略收益"].sum()
        win_rate = len(hist_df[hist_df["策略收益"] > 0]) / len(hist_df[hist_df["策略收益"] != 0]) if len(hist_df[hist_df["策略收益"] != 0]) > 0 else 0
        
        return {
            "近60天累计收益(%)": round(total_profit, 2),
            "胜率(%)": round(win_rate*100, 2),
            "交易次数": len(hist_df[hist_df["策略收益"] != 0])
        }
    except Exception as e:
        return None

# -------------------------- 3. Streamlit页面（含扩展功能） --------------------------
def main():
    st.title("📈 杨永兴短线选股工具（无Token版）")
    st.markdown("### 核心：16个月100万→1亿 | 无登录、实时刷新、全扩展功能")
    
    # 侧边栏：配置+扩展功能
    with st.sidebar:
        st.header("⚙️ 策略配置")
        DEFAULT_CONFIG["circ_mv_min"] = st.number_input("流通市值下限(亿)", min_value=10, max_value=100, value=50)
        DEFAULT_CONFIG["circ_mv_max"] = st.number_input("流通市值上限(亿)", min_value=100, max_value=500, value=200)
        DEFAULT_CONFIG["turnover_rate_min"] = st.slider("当日换手率下限(%)", 5, 15, 8)
        auto_refresh = st.checkbox("开启自动刷新", value=True)
        enable_notify = st.checkbox("开启买入信号桌面预警", value=True)
        
        st.divider()
        st.header("📊 扩展功能")
        # 历史回测入口
        backtest_code = st.text_input("输入股票代码回测（如600000）", "")
        if st.button("执行简单回测") and backtest_code:
            with st.spinner("回测中..."):
                backtest_result = backtest_simple(backtest_code)
                if backtest_result:
                    st.success("回测结果：")
                    st.write(f"近60天累计收益：{backtest_result['近60天累计收益(%)']}%")
                    st.write(f"胜率：{backtest_result['胜率(%)']}%")
                    st.write(f"交易次数：{backtest_result['交易次数']}")
                else:
                    st.info("回测数据不足")
    
    # 主页面
    placeholder = st.empty()
    while True:
        with placeholder.container():
            # 市场状态+时间
            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            market_status = "✅ 交易中" if is_market_open() else "❌ 非交易时间"
            st.subheader(f"当前时间：{current_time} | 市场状态：{market_status}")
            
            if not is_market_open():
                st.warning("⚠️ 非交易时间，数据为最新快照，自动刷新暂停")
            
            # 选股执行
            with st.spinner("筛选符合条件的股票..."):
                result_df = select_stocks()
            
            # 结果展示
            if len(result_df) > 0:
                st.success(f"🎉 筛选出 {len(result_df)} 只符合条件的股票（杨永兴策略）")
                
                # 核心选股表格
                st.dataframe(
                    result_df[["股票代码", "股票名称", "流通市值(亿)", "当日换手率(%)", "量比", 
                              "买入信号", "建议仓位(%)", "当前价格", "5%止盈价", "3%止损价"]],
                    use_container_width=True,
                    column_config={"买入信号": st.column_config.CheckboxColumn("买入信号")}
                )
                
                # 扩展1：买入信号预警
                buy_signal_stocks = result_df[result_df["买入信号"] == True]
                if len(buy_signal_stocks) > 0 and enable_notify and is_market_open():
                    notify_stocks = buy_signal_stocks["股票名称"].tolist()[:3]
                    send_notification(
                        title="📢 买入信号提醒",
                        message=f"以下股票符合买入条件：{','.join(notify_stocks)}"
                    )
                    st.markdown("### 🚨 买入信号预警")
                    st.dataframe(buy_signal_stocks[["股票代码", "股票名称", "当前价格", "5日均线", "建议仓位(%)"]], use_container_width=True)
                
                # 扩展2：可视化增强（K线+均线）
                st.markdown("### 📊 标的技术面可视化")
                selected_stock = st.selectbox("选择股票查看K线", result_df["股票名称"].tolist())
                selected_code = result_df[result_df["股票名称"] == selected_stock]["股票代码"].iloc[0]
                
                # 获取K线数据
                kline_df = ak.stock_zh_a_hist(
                    symbol=selected_code,
                    period="daily",
                    start_date=(datetime.now() - timedelta(days=30)).strftime("%Y%m%d"),
                    end_date=datetime.now().strftime("%Y%m%d"),
                    adjust="qfq"
                )
                kline_df["ma5"] = kline_df["收盘"].rolling(window=5).mean()
                kline_df["ma10"] = kline_df["收盘"].rolling(window=10).mean()
                kline_df["ma20"] = kline_df["收盘"].rolling(window=20).mean()
                
                # 绘制K线+均线
                fig = go.Figure(data=[
                    go.Candlestick(
                        x=kline_df["日期"],
                        open=kline_df["开盘"],
                        high=kline_df["最高"],
                        low=kline_df["最低"],
                        close=kline_df["收盘"],
                        name="K线"
                    ),
                    go.Scatter(x=kline_df["日期"], y=kline_df["ma5"], name="5日均线", line=dict(color="red", width=1)),
                    go.Scatter(x=kline_df["日期"], y=kline_df["ma10"], name="10日均线", line=dict(color="blue", width=1)),
                    go.Scatter(x=kline_df["日期"], y=kline_df["ma20"], name="20日均线", line=dict(color="green", width=1))
                ])
                fig.update_layout(title=f"{selected_stock}（{selected_code}）近30天K线", xaxis_rangeslider_visible=False)
                st.plotly_chart(fig, use_container_width=True)
                
            else:
                st.info("ℹ️ 暂无符合条件的股票")
        
        # 自动刷新逻辑
        if auto_refresh and is_market_open():
            time.sleep(REFRESH_INTERVAL)
            placeholder.empty()
        else:
            break

if __name__ == "__main__":
    main()
