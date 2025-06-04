import streamlit as st
import requests
import re
from bs4 import BeautifulSoup
import pyupbit
from pykrx import stock
from datetime import datetime, timedelta
import json
import yfinance as yf
import pandas as pd
import time
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import ccxt
import FinanceDataReader as fdr
import sqlite3
import hashlib
import os

# ----------------------
# 데이터베이스 초기화
# ----------------------
def init_db():
    if not os.path.exists('users.db'):
        conn = sqlite3.connect('users.db')
        c = conn.cursor()
        c.execute('''
            CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                email TEXT UNIQUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.commit()
        conn.close()

# ----------------------
# 비밀번호 해싱
# ----------------------
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

# ----------------------
# 사용자 인증
# ----------------------
def authenticate_user(username, password):
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute('SELECT * FROM users WHERE username = ? AND password = ?',
              (username, hash_password(password)))
    user = c.fetchone()
    conn.close()
    return user is not None

# ----------------------
# 사용자 등록
# ----------------------
def register_user(username, password, email):
    try:
        conn = sqlite3.connect('users.db')
        c = conn.cursor()
        c.execute('INSERT INTO users (username, password, email) VALUES (?, ?, ?)',
                 (username, hash_password(password), email))
        conn.commit()
        conn.close()
        return True
    except sqlite3.IntegrityError:
        return False

# ----------------------
# 주식 가격 조회 함수
# ----------------------
def get_stock_price(name):
    try:
        # 종목명으로 종목코드 찾기
        stock_list = fdr.StockListing('KRX')
        stock_info = stock_list[stock_list['Name'] == name]
        
        if stock_info.empty:
            st.warning(f"종목 '{name}'을(를) 찾을 수 없습니다.")
            return name, -1, None, None
            
        code = stock_info['Code'].iloc[0]
        
        # 현재가 조회
        today = datetime.now().strftime("%Y-%m-%d")
        yesterday = (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d")
        
        # 최근 데이터 조회
        df = fdr.DataReader(code, yesterday, today)
        
        if df.empty:
            st.warning("현재가 정보를 가져올 수 없습니다.")
            return name, -1, code, None
            
        # 가장 최근 거래일의 종가를 현재가로 사용
        price = df['Close'].iloc[-1]
        
        # 과거 데이터 조회 (최근 30일)
        try:
            start_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
            df = fdr.DataReader(code, start_date, today)
            
            if df.empty:
                st.warning("과거 데이터를 가져올 수 없습니다.")
                df = None
                
        except Exception as e:
            st.warning(f"과거 데이터 조회 중 오류 발생: {str(e)}")
            df = None
            
        return name, price, code, df
        
    except Exception as e:
        st.error(f"주식 가격 조회 중 오류 발생: {str(e)}")
        return name, -1, None, None

# ----------------------
# 코인 가격 조회 함수
# ----------------------
def get_crypto_price(name):
    try:
        # 업비트에서 사용 가능한 모든 코인 목록 가져오기
        tickers = pyupbit.get_tickers(fiat="KRW")
        
        # 한글 이름을 심볼로 변환
        name_mapping = {
            '비트코인': 'BTC',
            '이더리움': 'ETH',
            '리플': 'XRP',
            '도지코인': 'DOGE',
            '샌드박스': 'SAND',
            '에이다': 'ADA',
            '솔라나': 'SOL',
            '폴리곤': 'MATIC',
            '바이낸스코인': 'BNB',
            '트론': 'TRX'
        }
        
        # 한글 이름이 매핑에 있는 경우 심볼로 변환
        symbol = name_mapping.get(name, name.upper())
        ticker = f"KRW-{symbol}"
        
        if ticker not in tickers:
            st.warning(f"코인 '{name}'을(를) 찾을 수 없습니다.")
            return None, -1, None
            
        # 현재가 조회
        price = pyupbit.get_current_price(ticker)
        if price is None:
            st.warning("현재가 정보를 가져올 수 없습니다.")
            return ticker, -1, None
            
        # 과거 데이터 조회 (최근 30일)
        try:
            df = pyupbit.get_ohlcv(ticker, interval="day", count=30)
            if df is None or df.empty:
                st.warning("과거 데이터를 가져올 수 없습니다.")
                df = None
        except Exception as e:
            st.warning(f"과거 데이터 조회 중 오류 발생: {str(e)}")
            df = None
            
        return ticker, price, df
        
    except Exception as e:
        st.error(f"코인 가격 조회 중 오류 발생: {str(e)}")
        return None, -1, None

# ----------------------
# 코인 선물 가격 조회 함수
# ----------------------
def get_crypto_futures_price(name):
    try:
        # 한글 이름을 심볼로 변환 (바이낸스 선물 심볼 매핑)
        name_mapping = {
            '비트코인': 'BTC',
            '이더리움': 'ETH',
            '리플': 'XRP',
            '도지코인': 'DOGE',
            '샌드박스': 'SAND',
            '에이다': 'ADA',
            '솔라나': 'SOL',
            '폴리곤': 'MATIC',
            '바이낸스코인': 'BNB',
            '트론': 'TRX'
        }
        
        # 한글 이름이 매핑에 있는 경우 심볼로 변환
        symbol = name_mapping.get(name, name.upper())
        futures_symbol = f"{symbol}/USDT"  # 바이낸스 선물 심볼 형식
        
        # 바이낸스 선물 거래소 초기화
        exchange = ccxt.binance({
            'enableRateLimit': True,
            'options': {
                'defaultType': 'future'
            }
        })
        
        # 선물 시장 정보 조회
        markets = exchange.load_markets()
        
        # 사용 가능한 심볼 목록 출력 (디버깅용)
        available_symbols = [s for s in markets.keys() if 'USDT' in s]
        st.write(f"사용 가능한 선물 심볼: {available_symbols[:10]}...")  # 처음 10개만 표시
        
        if futures_symbol not in markets:
            st.warning(f"선물 '{name}'을(를) 찾을 수 없습니다. (시도한 심볼: {futures_symbol})")
            return None, -1, None
            
        # 현재가 조회
        ticker = exchange.fetch_ticker(futures_symbol)
        if ticker is None:
            st.warning("현재가 정보를 가져올 수 없습니다.")
            return futures_symbol, -1, None
            
        price = ticker['last']
        
        # 과거 데이터 조회 (최근 30일)
        try:
            # 1시간 간격으로 데이터 조회
            ohlcv = exchange.fetch_ohlcv(
                futures_symbol,
                timeframe='1h',
                limit=720  # 30일 * 24시간
            )
            
            if ohlcv:
                # DataFrame으로 변환
                df = pd.DataFrame(
                    ohlcv,
                    columns=['timestamp', 'open', 'high', 'low', 'close', 'volume']
                )
                df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
                df.set_index('timestamp', inplace=True)
            else:
                st.warning("과거 데이터를 가져올 수 없습니다.")
                df = None
                
        except Exception as e:
            st.warning(f"과거 데이터 조회 중 오류 발생: {str(e)}")
            df = None
            
        return futures_symbol, price, df
        
    except Exception as e:
        st.error(f"선물 가격 조회 중 오류 발생: {str(e)}")
        return None, -1, None

# ----------------------
# 가상 계좌 클래스 정의
# ----------------------
class VirtualAccount:
    def __init__(self, init_cash=0):
        self.cash = init_cash
        self.holdings = {}
        
    def deposit(self, amount):
        self.cash += amount

    def get_cash(self):
        return self.cash

    def buy(self, name, price, qty):
        cost = price * qty
        if self.cash >= cost:
            self.cash -= cost
            self.holdings[name] = self.holdings.get(name, 0) + qty
            return True
        return False

    def sell(self, name, price, qty):
        holding = self.holdings.get(name, 0)
        if holding >= qty:
            self.cash += price * qty
            self.holdings[name] = holding - qty
            return True
        return False

# ----------------------
# 화면 구성
# ----------------------
st.set_page_config(page_title="자동매매 시스템", layout="centered")

# 데이터베이스 초기화
init_db()

# 세션 상태 초기화
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
if 'username' not in st.session_state:
    st.session_state.username = None

# 로그인 상태가 아닐 경우 로그인/회원가입 화면 표시
if not st.session_state.logged_in:
    st.title("🔐 자동매매 시스템 로그인")
    
    # 탭 생성
    tab1, tab2 = st.tabs(["로그인", "회원가입"])
    
    with tab1:
        st.subheader("로그인")
        login_username = st.text_input("아이디", key="login_username")
        login_password = st.text_input("비밀번호", type="password", key="login_password")
        
        if st.button("로그인"):
            if authenticate_user(login_username, login_password):
                st.session_state.logged_in = True
                st.session_state.username = login_username
                st.success("로그인 성공!")
                st.experimental_rerun()
            else:
                st.error("아이디 또는 비밀번호가 올바르지 않습니다.")
    
    with tab2:
        st.subheader("회원가입")
        reg_username = st.text_input("아이디", key="reg_username")
        reg_password = st.text_input("비밀번호", type="password", key="reg_password")
        reg_password_confirm = st.text_input("비밀번호 확인", type="password", key="reg_password_confirm")
        reg_email = st.text_input("이메일", key="reg_email")
        
        if st.button("회원가입"):
            if reg_password != reg_password_confirm:
                st.error("비밀번호가 일치하지 않습니다.")
            elif len(reg_password) < 6:
                st.error("비밀번호는 6자 이상이어야 합니다.")
            else:
                if register_user(reg_username, reg_password, reg_email):
                    st.success("회원가입이 완료되었습니다. 로그인해주세요.")
                else:
                    st.error("이미 존재하는 아이디 또는 이메일입니다.")
    
    st.stop()

# 로그인 상태일 경우 기존 자동매매 시스템 표시
st.title(f"💰 자동매매 시스템 - {st.session_state.username}님 환영합니다!")

# 로그아웃 버튼
if st.sidebar.button("로그아웃"):
    st.session_state.logged_in = False
    st.session_state.username = None
    st.experimental_rerun()

# ----------------------
# 세션 상태 초기화
# ----------------------
if 'account' not in st.session_state:
    st.session_state.account = VirtualAccount()
if 'log' not in st.session_state:
    st.session_state.log = []
if 'stock_info' not in st.session_state:
    st.session_state.stock_info = {}
if 'crypto_info' not in st.session_state:
    st.session_state.crypto_info = {}
if 'futures_info' not in st.session_state:
    st.session_state.futures_info = {}

# ----------------------
# 사이드바 네비게이션
# ----------------------
st.sidebar.markdown("""
    <style>
    .sidebar-header {
        font-size: 24px;
        font-weight: bold;
        color: #000000;
        padding: 10px 0;
        border-bottom: 2px solid #1E88E5;
        margin-bottom: 20px;
    }
    .asset-section {
        background-color: #ffffff;
        padding: 15px;
        border-radius: 10px;
        margin: 10px 0;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    }
    .asset-title {
        font-size: 18px;
        font-weight: bold;
        color: #000000;
        margin-bottom: 15px;
        padding-bottom: 5px;
        border-bottom: 1px solid #e0e0e0;
    }
    .asset-item {
        padding: 8px 0;
        border-bottom: 1px solid #f0f0f0;
        color: #000000;
        font-size: 14px;
    }
    .total-assets {
        font-size: 20px;
        font-weight: bold;
        color: #000000;
        padding: 15px;
        background-color: #ffffff;
        border-radius: 10px;
        margin: 10px 0;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        border: 2px solid #1E88E5;
    }
    .cash-balance {
        font-size: 14px;
        color: #666666;
        margin-top: 5px;
        padding-top: 5px;
        border-top: 1px solid #e0e0e0;
    }
    .menu-section {
        margin-top: 30px;
        padding-top: 20px;
        border-top: 2px solid #e0e0e0;
    }
    .stRadio > div {
        padding: 10px;
        background-color: #ffffff;
        border-radius: 10px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    }
    </style>
    """, unsafe_allow_html=True)

st.sidebar.markdown('<div class="sidebar-header">📊 자산 현황</div>', unsafe_allow_html=True)

# 보유 자산 현황 표시
stock_holdings = st.session_state.account.holdings

# 총 자산 현황
total_assets = st.session_state.account.cash
if stock_holdings:
    for name, qty in stock_holdings.items():
        try:
            if name.startswith('KRW-'):
                symbol, price, _ = get_crypto_price(name.replace('KRW-', ''))
            else:
                _, price, _, _ = get_stock_price(name)
            if price != -1:
                total_assets += price * qty
        except:
            continue

st.sidebar.markdown(f'''
    <div class="total-assets">
        💰 총 자산: {total_assets:,.0f}원
        <div class="cash-balance">💵 보유 현금: {st.session_state.account.cash:,.0f}원</div>
    </div>
''', unsafe_allow_html=True)

# 주식 보유 현황
st.sidebar.markdown('<div class="asset-section">', unsafe_allow_html=True)
st.sidebar.markdown('<div class="asset-title">📈 주식 보유 현황</div>', unsafe_allow_html=True)

if stock_holdings:
    for name, qty in stock_holdings.items():
        if not name.startswith('KRW-'):  # 코인이 아닌 경우만 표시
            try:
                # 현재가 조회
                _, price, _, _ = get_stock_price(name)
                if price != -1:
                    total_value = price * qty
                    st.sidebar.markdown(f'<div class="asset-item">💰 {name}: {qty:,}주 ({total_value:,}원)</div>', unsafe_allow_html=True)
            except:
                st.sidebar.markdown(f'<div class="asset-item">💰 {name}: {qty:,}주</div>', unsafe_allow_html=True)
else:
    st.sidebar.markdown('<div class="asset-item">보유 주식 없음</div>', unsafe_allow_html=True)
st.sidebar.markdown('</div>', unsafe_allow_html=True)

# 코인 보유 현황
st.sidebar.markdown('<div class="asset-section">', unsafe_allow_html=True)
st.sidebar.markdown('<div class="asset-title">🪙 코인 보유 현황</div>', unsafe_allow_html=True)
if stock_holdings:
    for name, qty in stock_holdings.items():
        if name.startswith('KRW-'):  # 코인인 경우만 표시
            try:
                # 현재가 조회
                symbol, price, _ = get_crypto_price(name.replace('KRW-', ''))
                if price != -1:
                    total_value = price * qty
                    st.sidebar.markdown(f'<div class="asset-item">💎 {name}: {qty:.8f}개 ({total_value:,.0f}원)</div>', unsafe_allow_html=True)
            except:
                st.sidebar.markdown(f'<div class="asset-item">💎 {name}: {qty:.8f}개</div>', unsafe_allow_html=True)
else:
    st.sidebar.markdown('<div class="asset-item">보유 코인 없음</div>', unsafe_allow_html=True)
st.sidebar.markdown('</div>', unsafe_allow_html=True)

# 거래 유형 선택
st.sidebar.markdown('<div class="menu-section">', unsafe_allow_html=True)
st.sidebar.markdown('<div class="sidebar-header">💹 거래 유형</div>', unsafe_allow_html=True)
menu = st.sidebar.radio(
    "거래 유형을 선택하세요",
    ["주식 거래", "코인 현물 거래", "코인 선물 거래"],
    label_visibility="collapsed"
)
st.sidebar.markdown('</div>', unsafe_allow_html=True)

# ----------------------
# 입금 섹션
# ----------------------
st.subheader(f"현재 잔고: {st.session_state.account.get_cash():,} 원")
deposit_input = st.number_input("입금 금액 입력", min_value=0, step=1000, format="%d", key="deposit_input")
if st.button("입금", key="deposit_button"):
    amount = deposit_input
    st.session_state.account.deposit(amount)
    st.session_state.log.append(f"입금 완료: {amount:,}원")
    st.success(f"{amount:,}원 입금됨")
    st.experimental_rerun()

# ----------------------
# 주식 시세 조회 UI
# ----------------------
if menu == "주식 거래":
    st.header("📊 주식 시세 조회")
    if "stock_info" not in st.session_state:
        st.session_state.stock_info = {}
    if "show_chart" not in st.session_state:
        st.session_state.show_chart = False

    stock_name = st.text_input("주식 이름 입력 (예: 삼성전자)", key="stock_name")
    col1, col2 = st.columns([1, 1])
    
    with col1:
        if st.button("주식 시세 조회", key="stock_search"):
            if stock_name.strip() == "":
                st.warning("종목명을 입력해주세요.")
            else:
                name, price, code, df = get_stock_price(stock_name)
                if price != -1:
                    st.session_state.stock_info = {"name": name, "price": price, "code": code, "data": df}
                    st.session_state.log.append(f"주식 시세 조회 성공: [{name}] 현재가 {price:,}원 (코드: {code})")
                    st.session_state.show_chart = False
                else:
                    st.session_state.log.append("주식 정보 조회 실패")
                    st.error("주식 정보를 찾을 수 없습니다.")
    
    with col2:
        if st.session_state.stock_info and st.button("실시간 거래 차트 실행", key="show_stock_chart"):
            st.session_state.show_chart = True

    # 현재가 정보 표시
    if st.session_state.stock_info:
        name = st.session_state.stock_info["name"]
        price = st.session_state.stock_info["price"]
        code = st.session_state.stock_info["code"]
        
        col1, col2 = st.columns([1, 2])
        with col1:
            st.metric(label=f"[{name}] 현재가", value=f"{price:,}원")
        with col2:
            st.write(f"종목코드: {code}")
        
        # 차트 표시
        if st.session_state.show_chart and st.session_state.stock_info["data"] is not None:
            df = st.session_state.stock_info["data"]
            # 캔들스틱 차트 생성
            fig = make_subplots(rows=2, cols=1, shared_xaxes=True, 
                              vertical_spacing=0.03, 
                              row_heights=[0.7, 0.3])

            # 캔들스틱 차트 추가
            fig.add_trace(go.Candlestick(x=df.index,
                                       open=df['Open'],
                                       high=df['High'],
                                       low=df['Low'],
                                       close=df['Close'],
                                       name='OHLC'),
                        row=1, col=1)

            # 거래량 차트 추가
            fig.add_trace(go.Bar(x=df.index, y=df['Volume'],
                               name='Volume'),
                        row=2, col=1)

            # 차트 레이아웃 설정
            fig.update_layout(
                title=f'{name} 주가 차트',
                yaxis_title='주가',
                yaxis2_title='거래량',
                xaxis_rangeslider_visible=False,
                height=800
            )

            # 차트 표시
            st.plotly_chart(fig, use_container_width=True)
            
            # 실시간 업데이트 버튼
            if st.button("실시간 업데이트 시작", key="realtime_update"):
                st.session_state.realtime_update = True
                while st.session_state.realtime_update:
                    # 5분마다 데이터 업데이트
                    time.sleep(300)
                    name, price, code, df = get_stock_price(stock_name)
                    if price != -1:
                        st.session_state.stock_info = {"name": name, "price": price, "code": code, "data": df}
                        st.experimental_rerun()

    # 거래 방식 선택: "수량 기준" 또는 "금액 기준"
    trade_method_stock = st.radio("거래 방식 선택", ["수량 기준", "금액 기준"], horizontal=True, key="stock_trade_method")
    if trade_method_stock == "수량 기준":
        stock_qty = st.number_input("주식 수량 입력", min_value=1, step=1, key="stock_qty")
    else:
        trade_amount_stock = st.number_input("거래 금액 입력", min_value=0, step=1000, format="%d", key="trade_amount_stock")

    action_stock = st.radio("주식 거래 선택", ["매수", "매도"], horizontal=True, key="stock_trade_action")

    if st.button("주식 거래 실행", key="stock_trade_execute"):
        if not st.session_state.stock_info:
            st.error("주식 정보를 먼저 조회하세요.")
        else:
            name = st.session_state.stock_info["name"]
            price = st.session_state.stock_info["price"]
            
            if trade_method_stock == "수량 기준":
                qty = stock_qty
            else:
                qty = trade_amount_stock // price
                if qty < 1:
                    st.error("입력한 금액이 1주 가격보다 작습니다.")
                    st.stop()
                    
            if action_stock == "매수":
                if st.session_state.account.buy(name, price, qty):
                    st.session_state.log.append(f"주식 매수 완료: {qty}주 @ {price:,}원")
                    st.success(f"[매수 완료] {qty}주 @ {price:,}원")
                else:
                    st.session_state.log.append("주식 매수 실패: 잔고 부족")
                    st.error("[매수 실패] 잔고 부족")
            elif action_stock == "매도":
                if st.session_state.account.sell(name, price, qty):
                    st.session_state.log.append(f"주식 매도 완료: {qty}주 @ {price:,}원")
                    st.success(f"[매도 완료] {qty}주 @ {price:,}원")
                else:
                    st.session_state.log.append("주식 매도 실패: 보유 수량 부족")
                    st.error("[매도 실패] 보유 수량 부족")
            st.experimental_rerun()

# ----------------------
# 코인 현물 시세 조회 UI
# ----------------------
elif menu == "코인 현물 거래":
    st.header("🪙 코인 현물 시세 조회")
    if "crypto_info" not in st.session_state:
        st.session_state.crypto_info = {}

    crypto_name = st.text_input("코인 이름 입력 (예: 비트코인)", key="crypto_name")
    col1, col2 = st.columns([1, 1])
    
    with col1:
        if st.button("코인 시세 조회", key="crypto_search"):
            symbol, cprice, df = get_crypto_price(crypto_name)
            if cprice != -1:
                st.session_state.crypto_info = {"symbol": symbol, "price": cprice, "data": df, "name": crypto_name}
                st.session_state.log.append(f"코인 시세 조회 성공: [{crypto_name}] 현재가 {cprice:,}원 ({symbol})")
            else:
                st.session_state.log.append("코인 정보 조회 실패")
                st.error("코인 정보를 찾을 수 없습니다.")

    # 현재가 정보 표시
    if st.session_state.crypto_info:
        symbol = st.session_state.crypto_info["symbol"]
        cprice = st.session_state.crypto_info["price"]
        crypto_name = st.session_state.crypto_info["name"]
        
        st.success(f"[{crypto_name}] 현재가: {cprice:,}원 ({symbol})")
        
        # 차트 표시 버튼
        if st.button("실시간 거래 차트 실행", key="show_crypto_chart"):
            df = st.session_state.crypto_info["data"]
            if df is not None:
                # 캔들스틱 차트 생성
                fig = make_subplots(rows=2, cols=1, shared_xaxes=True, 
                                  vertical_spacing=0.03, 
                                  row_heights=[0.7, 0.3])

                # 캔들스틱 차트 추가
                fig.add_trace(go.Candlestick(x=df.index,
                                           open=df['open'],
                                           high=df['high'],
                                           low=df['low'],
                                           close=df['close'],
                                           name='OHLC'),
                            row=1, col=1)

                # 거래량 차트 추가
                fig.add_trace(go.Bar(x=df.index, y=df['volume'],
                                   name='Volume'),
                            row=2, col=1)

                # 차트 레이아웃 설정
                fig.update_layout(
                    title=f'{crypto_name} 가격 차트',
                    yaxis_title='가격 (KRW)',
                    yaxis2_title='거래량',
                    xaxis_rangeslider_visible=False,
                    height=800
                )

                # 차트 표시
                st.plotly_chart(fig, use_container_width=True)
                
                # 실시간 업데이트 버튼
                if st.button("실시간 업데이트 시작", key="crypto_realtime_update"):
                    st.session_state.crypto_realtime_update = True
                    while st.session_state.crypto_realtime_update:
                        # 5분마다 데이터 업데이트
                        time.sleep(300)
                        symbol, cprice, df = get_crypto_price(crypto_name)
                        if cprice != -1:
                            st.session_state.crypto_info = {"symbol": symbol, "price": cprice, "data": df, "name": crypto_name}
                            st.experimental_rerun()

    # 거래 방식 선택: "수량 기준" 또는 "금액 기준"
    trade_method = st.radio("거래 방식 선택", ["수량 기준", "금액 기준"], horizontal=True, key="crypto_trade_method")
    if trade_method == "수량 기준":
        trade_qty = st.number_input("코인 수량 입력", min_value=0.0, step=0.0001, format="%.8f", key="crypto_trade_qty")
    else:
        trade_amount = st.number_input("거래 금액 입력", min_value=0, step=1000, format="%d", key="crypto_trade_amount")

    action = st.radio("코인 거래 선택", ["코인 매수", "코인 매도"], horizontal=True, key="crypto_trade_action")

    if st.button("코인 거래 실행", key="crypto_trade_execute"):
        crypto_info = st.session_state.get("crypto_info")
        if not crypto_info:
            st.error("코인 정보를 먼저 조회하세요.")
        else:
            symbol = crypto_info["symbol"]
            cprice = crypto_info["price"]
            crypto_name = crypto_info["name"]
            
            if trade_method == "수량 기준":
                qty = trade_qty
            else:
                qty = trade_amount / cprice
            
            if qty <= 0:
                st.error("거래할 수량이 0 이하입니다.")
            else:
                if action == "코인 매수":
                    if st.session_state.account.buy(symbol, cprice, qty):
                        st.session_state.log.append(f"코인 매수 완료: {qty}개 @ {cprice:,}원")
                        st.success(f"[코인 매수 완료] {qty}개 @ {cprice:,}원")
                        st.session_state.crypto_info = None  # 거래 후 정보 초기화
                        st.experimental_rerun()
                    else:
                        st.session_state.log.append("코인 매수 실패: 잔고 부족")
                        st.error("[코인 매수 실패] 잔고 부족")
                elif action == "코인 매도":
                    if st.session_state.account.sell(symbol, cprice, qty):
                        st.session_state.log.append(f"코인 매도 완료: {qty}개 @ {cprice:,}원")
                        st.success(f"[코인 매도 완료] {qty}개 @ {cprice:,}원")
                        st.session_state.crypto_info = None  # 거래 후 정보 초기화
                        st.experimental_rerun()
                    else:
                        st.session_state.log.append("코인 매도 실패: 보유 수량 부족")
                        st.error("[코인 매도 실패] 보유 수량 부족")

# ----------------------
# 코인 선물 시세 조회 UI
# ----------------------
elif menu == "코인 선물 거래":
    st.header("📈 코인 선물 시세 조회")
    if "futures_info" not in st.session_state:
        st.session_state.futures_info = {}

    futures_name = st.text_input("선물 코인 이름 입력 (예: 도지코인, 비트코인)", key="futures_name")
    col1, col2 = st.columns([1, 1])
    
    with col1:
        if st.button("선물 시세 조회", key="futures_search"):
            symbol, fprice, df = get_crypto_futures_price(futures_name)
            if fprice != -1:
                st.session_state.futures_info = {"symbol": symbol, "price": fprice, "data": df, "name": futures_name}
                # 코인 현물 정보도 함께 업데이트
                st.session_state.crypto_info = {"symbol": f"KRW-{symbol.split('/')[0]}", "price": fprice, "data": df, "name": futures_name}
                st.session_state.log.append(f"선물 시세 조회 성공: [{futures_name}] 현재가 {fprice:,}원 ({symbol})")
            else:
                st.session_state.log.append("선물 정보 조회 실패")
                st.error("선물 정보를 찾을 수 없습니다.")

    # 현재가 정보 표시
    if st.session_state.futures_info:
        symbol = st.session_state.futures_info["symbol"]
        fprice = st.session_state.futures_info["price"]
        futures_name = st.session_state.futures_info["name"]
        
        st.success(f"[{futures_name}] 현재가: {fprice:,}원 ({symbol})")
        
        # 차트 표시 버튼
        if st.button("실시간 거래 차트 실행", key="show_futures_chart"):
            df = st.session_state.futures_info["data"]
            if df is not None:
                # 캔들스틱 차트 생성
                fig = make_subplots(rows=2, cols=1, shared_xaxes=True, 
                                  vertical_spacing=0.03, 
                                  row_heights=[0.7, 0.3])

                # 캔들스틱 차트 추가
                fig.add_trace(go.Candlestick(x=df.index,
                                           open=df['open'],
                                           high=df['high'],
                                           low=df['low'],
                                           close=df['close'],
                                           name='OHLC'),
                            row=1, col=1)

                # 거래량 차트 추가
                fig.add_trace(go.Bar(x=df.index, y=df['volume'],
                                   name='Volume'),
                            row=2, col=1)

                # 차트 레이아웃 설정
                fig.update_layout(
                    title=f'{futures_name} 선물 가격 차트',
                    yaxis_title='가격 (KRW)',
                    yaxis2_title='거래량',
                    xaxis_rangeslider_visible=False,
                    height=800
                )

                # 차트 표시
                st.plotly_chart(fig, use_container_width=True)
                
                # 실시간 업데이트 버튼
                if st.button("실시간 업데이트 시작", key="futures_realtime_update"):
                    st.session_state.futures_realtime_update = True
                    while st.session_state.futures_realtime_update:
                        # 5분마다 데이터 업데이트
                        time.sleep(300)
                        symbol, fprice, df = get_crypto_futures_price(futures_name)
                        if fprice != -1:
                            st.session_state.futures_info = {"symbol": symbol, "price": fprice, "data": df, "name": futures_name}
                            st.session_state.crypto_info = {"symbol": f"KRW-{symbol.split('/')[0]}", "price": fprice, "data": df, "name": futures_name}
                            st.experimental_rerun()

    # 선물 거래 방식 선택: "수량 기준" 또는 "금액 기준"
    futures_trade_method = st.radio("선물 거래 방식 선택", ["수량 기준", "금액 기준"], horizontal=True, key="futures_trade_method")
    if futures_trade_method == "수량 기준":
        futures_qty = st.number_input("선물 수량 입력", min_value=0.0, step=0.0001, format="%.8f", key="futures_qty")
    else:
        futures_amount = st.number_input("거래 금액 입력", min_value=0, step=1000, format="%d", key="futures_amount")

    futures_action = st.radio("선물 거래 선택", ["선물 매수", "선물 매도"], horizontal=True, key="futures_trade_action")

    if st.button("선물 거래 실행", key="futures_trade_execute"):
        futures_info = st.session_state.get("futures_info")
        if not futures_info:
            st.error("선물 정보를 먼저 조회하세요.")
        else:
            symbol = futures_info["symbol"]
            fprice = futures_info["price"]
            futures_name = futures_info["name"]
            
            if futures_trade_method == "수량 기준":
                qty = futures_qty
            else:
                qty = futures_amount / fprice
            
            if qty <= 0:
                st.error("거래할 수량이 0 이하입니다.")
            else:
                # 선물 거래용 심볼을 현물 거래용 심볼로 변환
                spot_symbol = f"KRW-{symbol.split('/')[0]}"
                
                if futures_action == "선물 매수":
                    if st.session_state.account.buy(spot_symbol, fprice, qty):
                        st.session_state.log.append(f"선물 매수 완료: {qty}개 @ {fprice:,}원")
                        st.success(f"[선물 매수 완료] {qty}개 @ {fprice:,}원")
                        st.experimental_rerun()  # 자산 현황 업데이트를 위해 페이지 새로고침
                    else:
                        st.session_state.log.append("선물 매수 실패: 잔고 부족")
                        st.error("[선물 매수 실패] 잔고 부족")
                elif futures_action == "선물 매도":
                    if st.session_state.account.sell(spot_symbol, fprice, qty):
                        st.session_state.log.append(f"선물 매도 완료: {qty}개 @ {fprice:,}원")
                        st.success(f"[선물 매도 완료] {qty}개 @ {fprice:,}원")
                        st.experimental_rerun()  # 자산 현황 업데이트를 위해 페이지 새로고침
                    else:
                        st.session_state.log.append("선물 매도 실패: 보유 수량 부족")
                        st.error("[선물 매도 실패] 보유 수량 부족")

# ----------------------
# 실행 로그 출력
# ----------------------
st.markdown("### 실행 로그")
col1, col2 = st.columns([3, 1])
with col1:
    if st.session_state.log:
        for log in st.session_state.log:
            st.write(log)
    else:
        st.write("로그가 없습니다.")
with col2:
    if st.button("로그 삭제", key="clear_log"):
        st.session_state.log = []
        st.experimental_rerun()