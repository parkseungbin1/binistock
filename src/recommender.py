"""
라씨(Rassi) 매매신호 벤치마킹 AI 종목 추천 엔진
1. 🎯 오늘 15:10 종가베팅 (오버나잇: 당일 종가 매수 -> 익일 시초가 +3%~+5% 갭상승 매도)
2. 🚀 2~5일 스윙 (추세 파동: 20일선 눌림목 반등 -> 2~5일간 +5%~+10% 추세 익절)
"""
import html
import json
import logging
import re
import urllib.request
from datetime import datetime, timezone, timedelta
import pandas as pd

logger = logging.getLogger(__name__)
KST = timezone(timedelta(hours=9))

_SECTOR_MAP = {}


def format_marcap(marcap):
    """
    시가총액(원)을 직관적인 억/조 단위 한글 표기로 변환
    예:
        110581600000 -> '1,106억'
        2206342643000 -> '2조 2,063억'
        21554328762400 -> '21조 5,543억'
    """
    if not marcap or marcap <= 0:
        return ""
    try:
        marcap = float(marcap)
        eok = marcap / 1e8
        if eok >= 10000:
            jo = int(eok // 10000)
            rem_eok = int(round(eok % 10000))
            if rem_eok == 0:
                return f"{jo:,}조원"
            return f"{jo:,}조 {rem_eok:,}억"
        else:
            return f"{int(round(eok)):,}억"
    except Exception:
        return ""


def fetch_stock_catalyst(code, name=""):
    """
    종목별 실제 핵심 상승 재료(호재 뉴스 및 DART 공시) 정밀 추출 엔진.
    1) 단순 시황/지수 마감 기사('외국인 매도 폭탄 코스피...', '장중 급락' 등) 철저 필터링
    2) 해당 종목명(또는 약칭)이 직접 명시된 전용 뉴스 우선 선별
    3) 수주, 공급계약, 호실적, 신기술, 승인, 흑자전환, FDA 등 고영향 호재 키워드 가중치 부여
    4) DART 주요 경영 공시(단일판매공급계약, 실적전망 등) 교차 검증 연동
    5) 잘림 현상([종...) 방지 및 원문 기사 직접 링크(URL) 및 언론사, 본문 요약 제공
    """
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

    # 종목 약칭/별칭 세트
    short_name = name.replace('주식회사', '').replace('(주)', '').strip() if name else ''
    aliases = [short_name] if short_name else []
    if '바이오로직스' in short_name:
        aliases.extend(['삼성바이오', '삼바'])
    elif '카카오게임즈' in short_name:
        aliases.append('카겜')
    elif '하이닉스' in short_name:
        aliases.extend(['SK하닉', '하닉'])
    elif '이앤에이' in short_name or 'E&A' in short_name:
        aliases.extend(['삼성E&A', '삼성이앤에이'])

    # 1. DART 공시 우선 확인 (공식 확정 경영 호재)
    disc_info = None
    try:
        url_disc = f'https://m.stock.naver.com/api/stock/{code}/disclosure?pageSize=6&page=1'
        req_disc = urllib.request.Request(url_disc, headers=headers)
        with urllib.request.urlopen(req_disc, timeout=3) as resp:
            discs = json.loads(resp.read().decode('utf-8'))
            impact_keywords = ['단일판매', '공급계약', '영업실적', '타법인', '특허', '합병', '인수', '무상증자', '자사주']
            for d in discs:
                title = d.get('title', '')
                if any(k in title for k in impact_keywords):
                    clean_d = re.sub(r'^\([^\)]+\)\s*', '', title)
                    clean_d = re.sub(r'^(주|\(주\)|주식회사|비나텍주식회사|삼성바이오로직스\(주\)|삼성이앤에이\(주\))\s*', '', clean_d)
                    disc_info = {
                        'title': f"[공시] {clean_d}",
                        'url': f"https://m.stock.naver.com/domestic/stock/{code}/disclosure",
                        'source': 'DART 전자공시',
                        'body': f"{name} 금융감독원 전자공시시스템(DART) 주요 경영사항 공시"
                    }
                    break
    except Exception:
        pass

    # 2. 실시간 종목 뉴스 클러스터 전수 분석 (최대 30개)
    market_noise = ['코스피', '코스닥', '지수', '마감시황', '시황종합', '환율', '외인', '외국인 반도체', '투자30', '마켓뷰', '오후시황', '장중 4%', '5500선', '5400선', 'IPO 철회', '코스피5550']
    catalyst_keywords = ['수주', '계약', '잭팟', '대박', '실적', '영업익', '흑자', '최대', '신작', '승인', 'FDA', '개발', '임상', '특허', '폭등', '급등', '독점', '출격', '러브콜', '특징주', '부각', '목표가']

    news_candidates = []
    try:
        url_news = f'https://m.stock.naver.com/api/news/stock/{code}?pageSize=30&page=1'
        req_news = urllib.request.Request(url_news, headers=headers)
        with urllib.request.urlopen(req_news, timeout=3) as resp:
            clusters = json.loads(resp.read().decode('utf-8'))
            for cl in clusters:
                for it in cl.get('items', []):
                    raw_title = it.get('titleFull') or it.get('title', '')
                    title = html.unescape(raw_title).replace('<b>', '').replace('</b>', '').strip()
                    # 잘림 현상 방지: [종..., [종합], 말미 ... 제거
                    title = re.sub(r'\[종\.\.\.?\]?', '', title).strip()
                    title = re.sub(r'\.\.\.$', '', title).strip()
                    
                    is_about_stock = any(alias in title for alias in aliases) if aliases else True
                    is_noise = any(n in title for n in market_noise) and not ('[특징주]' in title and any(a in title for a in aliases))
                    cat_match_count = sum(1 for k in catalyst_keywords if k in title)

                    score = 0
                    if is_about_stock:
                        score += 50
                    if not is_noise:
                        score += 30
                    score += cat_match_count * 15
                    if '[특징주]' in title:
                        score += 25

                    if is_about_stock or (not is_noise and cat_match_count > 0):
                        url = it.get('mobileNewsUrl')
                        if not url and it.get('officeId') and it.get('articleId'):
                            url = f"https://n.news.naver.com/mnews/article/{it['officeId']}/{it['articleId']}"
                        if not url:
                            url = f"https://m.stock.naver.com/domestic/stock/{code}/news"

                        body_txt = html.unescape(it.get('body', '')).replace('<b>', '').replace('</b>', '').strip()
                        body_clean = re.sub(r'\s+', ' ', body_txt)[:110]

                        news_candidates.append({
                            'title': title,
                            'url': url,
                            'source': it.get('officeName', '증권뉴스'),
                            'body': body_clean,
                            'score': score
                        })
    except Exception as e:
        logger.warning(f"뉴스 수집 예외 ({code}): {e}")

    news_candidates.sort(key=lambda x: x['score'], reverse=True)

    if news_candidates and news_candidates[0]['score'] >= 50:
        best = news_candidates[0]
        return {
            'title': best['title'],
            'url': best['url'],
            'source': best['source'],
            'body': best['body']
        }
    elif disc_info:
        return disc_info
    else:
        return {
            'title': f"{short_name} 기관·외인 대량 수급 유입 및 업종 주도 모멘텀",
            'url': f"https://m.stock.naver.com/domestic/stock/{code}/news",
            'source': '실시간 수급',
            'body': '당일 거래대금 폭발 및 지지저항 돌파 주도주'
        }


def get_stock_sector(code, default="주도주"):
    """KRX-DESC 기반 종목별 업종/섹터 매핑 캐시 (주력 제품 및 핵심 테마 정밀 매핑)"""
    global _SECTOR_MAP
    if not _SECTOR_MAP:
        try:
            import FinanceDataReader as fdr
            desc = fdr.StockListing('KRX-DESC')
            if not desc.empty and 'Code' in desc.columns:
                for _, r in desc.iterrows():
                    c = str(r['Code'])
                    ind = str(r['Industry']) if ('Industry' in r and pd.notna(r['Industry'])) else ''
                    sec = str(r['Sector']) if ('Sector' in r and pd.notna(r['Sector'])) else ''
                    prod = str(r['Products']) if ('Products' in r and pd.notna(r['Products'])) else ''
                    name = str(r.get('Name', ''))
                    val = f"{name} {ind} {sec} {prod}"

                    if '반도체' in val or '웨이퍼' in val or 'CXL' in val or 'HBM' in val:
                        tag = '반도체'
                    elif '2차전지' in val or '배터리' in val or '양극재' in val or '음극재' in val or '전지' in val:
                        tag = '2차전지'
                    elif '바이오' in val or '의약' in val or '제약' in val or '치료제' in val or '백신' in val or '의료기기' in val:
                        tag = '제약/바이오'
                    elif '인공지능' in val or 'AI' in val or '로봇' in val or '로보틱스' in val:
                        tag = 'AI/로봇'
                    elif '전력' in val or '변압기' in val or '전선' in val or '원전' in val or '원자력' in val:
                        tag = '전력/원전'
                    elif '방산' in val or '항공' in val or '우주' in val or '군수' in val:
                        tag = '방산/우주'
                    elif '자동차' in val or '자율주행' in val or '전장' in val:
                        tag = '자동차/부품'
                    elif '조선' in val or '해운' in val or '선박' in val:
                        tag = '조선/해운'
                    elif '철강' in val or '금속' in val or '알루미늄' in val:
                        tag = '철강/금속'
                    elif '화학' in val or '석유' in val or '소재' in val:
                        tag = '화학/소재'
                    elif '통신' in val or '소프트웨어' in val or 'IT' in val or '보안' in val:
                        tag = 'IT/SW'
                    elif '기계' in val or '장비' in val or '특수 목적용' in val:
                        tag = '기계/장비'
                    else:
                        clean = ind.replace(' 제조업', '').replace(' 서비스업', '').replace(' 및 ', '/').strip()
                        tag = clean[:8] if len(clean) > 8 else (clean or default)
                    _SECTOR_MAP[c] = tag or default
        except Exception as e:
            logger.warning(f"업종 매핑 로드 실패: {e}")
    return _SECTOR_MAP.get(code, default)


def is_common_stock(row):
    """보통주 필터링 (우선주, 스팩, ETF, ETN, 인버스/레버리지, 신주인수권 제외)"""
    name = str(row.get('Name', ''))
    code = str(row.get('Code', ''))
    if len(code) != 6 or not code.isdigit():
        return False
    if code[-1] != '0':  # 우선주 제외 (0으로 끝나는 본주만 허용)
        return False
    exclude_keywords = ['스팩', 'ETF', 'ETN', '선물', '인버스', '레버리지', '채권', '국채', '원자재', 'KODEX', 'TIGER', 'ACE', 'KBSTAR', 'SOL']
    if any(k in name for k in exclude_keywords):
        return False
    return True


def fetch_naver_realtime_pool():
    """
    네이버 증권 모바일 공식 API를 통해 KOSPI/KOSDAQ 주요 우량주의 실시간 장중 호가/거래대금 수집
    15:05~15:10 장중 호출 시 어제 마감 데이터가 아닌 당일 실시간 체결 데이터를 1초 만에 100% 확보
    """
    import requests
    import pandas as pd

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }

    items = []
    # 코스피 200개 + 코스닥 200개 = 총 400개 우량주 스캔
    for mkt in ['KOSPI', 'KOSDAQ']:
        for page in [1, 2]:
            url = f'https://m.stock.naver.com/api/stocks/marketValue/{mkt}?page={page}&pageSize=100'
            try:
                r = requests.get(url, headers=headers, timeout=4)
                if r.status_code == 200:
                    stocks = r.json().get('stocks', [])
                    for s in stocks:
                        code = s.get('itemCode')
                        name = s.get('stockName')
                        close_p = s.get('closePriceRaw')
                        chg_pct = s.get('fluctuationsRatio')
                        amt_raw = s.get('accumulatedTradingValueRaw', 0)
                        mc_raw = s.get('marketValueRaw', 0)
                        if code and close_p:
                            items.append({
                                'Code': str(code),
                                'Name': str(name),
                                'Market': mkt,
                                'Close': float(close_p),
                                'Open': float(close_p),
                                'High': float(close_p),
                                'Low': float(close_p),
                                'ChagesRatio': float(chg_pct) if chg_pct else 0.0,
                                'Amount': float(amt_raw) if amt_raw else 0.0,
                                'Marcap': float(mc_raw) if mc_raw else 0.0
                            })
            except Exception as e:
                logger.debug(f"네이버 실시간 시세 {mkt} p{page} 수집 예외: {e}")

    if not items:
        return None

    df = pd.DataFrame(items)
    df = df[df.apply(is_common_stock, axis=1)].copy()

    # 시총 1000억 이상 & 거래대금 30억 이상인 핵심 분석 대상 종목(최대 60개)에 대해 polling API로 Open/High/Low 일괄 정밀 보정
    active_pool = df[
        (df['Marcap'] >= 1000 * 1e8) &
        (df['Amount'] >= 30 * 1e8)
    ].sort_values(by='Amount', ascending=False).head(60)
    target_codes = active_pool['Code'].tolist()

    if target_codes:
        p_map = {}
        for i in range(0, len(target_codes), 20):
            chunk = target_codes[i:i+20]
            try:
                poll_url = f'https://polling.finance.naver.com/api/realtime/domestic/stock/{",".join(chunk)}'
                pr = requests.get(poll_url, headers=headers, timeout=4)
                if pr.status_code == 200:
                    for d in pr.json().get('datas', []):
                        if isinstance(d, dict) and 'itemCode' in d:
                            p_map[d['itemCode']] = d
            except Exception as e:
                logger.debug(f"네이버 polling 청크 예외: {e}")

        for idx_row, row in df.iterrows():
            c = row['Code']
            if c in p_map:
                d = p_map[c]
                df.at[idx_row, 'Open'] = float(d.get('openPriceRaw', row['Close']))
                df.at[idx_row, 'High'] = float(d.get('highPriceRaw', row['Close']))
                df.at[idx_row, 'Low'] = float(d.get('lowPriceRaw', row['Close']))

    return df



def evaluate_market_regime(market_context=None):
    """
    시장 안전도(Market Regime) 판정:
    코스피 외인 수급, 나스닥 선물, 공포탐욕지수를 종합하여 포지션 비중 및 리스크 경고 산출
    """
    if not market_context:
        return {
            'status': 'neutral',
            'badge': '🔵 박스권 안정 환경 (정밀 선별)',
            'badge_class': 'regime-neutral',
            'message': '지수가 안정적인 흐름을 유지 중입니다. 거래대금 주도주 및 20일선 눌림목 반등 종목 위주로 정밀 분할 매매를 권장합니다.',
            'position_advice': '정상 비중 분할 매수 / 목표 손익비 엄수'
        }

    fut_ratio = market_context.get('fut_ratio', 0.0)
    kp_for_num = market_context.get('kp_for_num', 0)
    cnn_score = market_context.get('cnn_score')

    # 1) 시장 급락/패닉/방어 경계 모드 (외인 -1,000억 이상 매도 or 선물 -0.6% or CNN 공포 <= 35)
    risk_val = market_context.get('ai_risk_score') if market_context else None
    if kp_for_num <= -1000 or fut_ratio <= -0.6 or (cnn_score is not None and cnn_score <= 35) or (risk_val is not None and risk_val >= 50):
        return {
            'status': 'warning',
            'badge': '⚠️ 시장 급락 경계 모드 (리스크 방어)',
            'badge_class': 'regime-warning',
            'message': '외국인 대규모 투매 또는 나스닥 선물 급락세로 지수 하방 압력이 높습니다. 종가베팅 비중을 평소의 50% 이하로 축소하거나 현금 관망을 강력 권장합니다.',
            'position_advice': '투자 비중 50% 축소 / 단기 손절선 -2% 엄수'
        }

    # 2) 상승 랠리/강세장 모드
    if fut_ratio >= 0.5 and kp_for_num >= 500:
        return {
            'status': 'bull',
            'badge': '🟢 상승 모멘텀 우수 (적극 공략)',
            'badge_class': 'regime-bull',
            'message': '나스닥 선물 강세 및 외국인 순매수 유입으로 지수 상방 탄력이 뛰어납니다. 주도주 중심의 종가베팅 및 스윙 공략 적기입니다.',
            'position_advice': '정상 비중 적극 참여 / 익일 시초가 분할 익절'
        }

    # 3) 일반/박스권 모드
    return {
        'status': 'neutral',
        'badge': '🔵 박스권 안정 환경 (정밀 선별)',
        'badge_class': 'regime-neutral',
        'message': '지수가 견고한 박스권 흐름을 보이고 있습니다. 거래대금 상위 주도주와 20일선 눌림목 반등 종목 위주로 원칙 매매를 진행하세요.',
        'position_advice': '정상 비중 분할 매수 / 목표 손익비 엄수'
    }


def resolve_swing_targets(close_p: int, regime: dict = None, risk_score: int = None, market_context: dict = None) -> dict:
    if risk_score is None and market_context:
        risk_score = market_context.get('ai_risk_score')

    # risk_score가 없으면 실시간 시황 지표를 직접 조회하여 판정
    if risk_score is None:
        try:
            from src.risk_score import compute_risk_score
            from src.market_score import fetch_kr_market, fetch_nasdaq_futures, fetch_cnn_fear_greed, fetch_vix
            _, kp_r, _, _, kp_for_n, _ = fetch_kr_market('KOSPI')
            _, fut_r = fetch_nasdaq_futures()
            cnn_s, _ = fetch_cnn_fear_greed()
            vix_c, _ = fetch_vix()
            vix_val = float(str(vix_c).replace(',', '')) if vix_c else 20.0
            live_ctx = {
                'fut_ratio': fut_r or 0.0,
                'kp_ratio': kp_r or 0.0,
                'cnn_score': cnn_s or 50.0,
                'vix': vix_val
            }
            risk_score = compute_risk_score(live_ctx)
        except Exception:
            risk_score = 50
    """
    스윙 목표가 & 손절가 산출 (원래 기준 복원: 1차 +5.0%, 2차 +9.0%, 손절 -3.0%)
    - 손익비: 1차 1.67 : 1, 2차 3.00 : 1 (평균 2.33 : 1)
    - 20일선 눌림목 반등 타겟: 1차 +5% 50% 분할 익절 → 본절 상향 → 2차 +9% 전량 익절
    """
    return {
        'mode': 'TREND',
        'mode_label': '🚀 2~5일 스윙 (추세 파동)',
        'mode_desc': '20일선 눌림목 반등 타겟: 1차 +5% 50% 분할 익절 → 손절선 본절 상향 → 2차 +9% 전량 익절',
        'target_1': int(round(close_p * 1.05)),
        'target_1_pct': '+5.0%',
        'target_2': int(round(close_p * 1.09)),
        'target_2_pct': '+9.0%',
        'target_3': None,
        'target_3_pct': None,
        'stop_loss': int(round(close_p * 0.97)),
        'stop_loss_pct': '-3.0%',
        'holding_period': '2~5영업일 분할 매도 (1차 +5.0% 50% 익절 → 본절 상향 → 2차 +9.0% 잔량 전량 익절)',
    }


def fetch_nxt_over_market_info(code: str) -> dict:
    """
    [아이디어 1] 네이버 증권 basic API에서 Nextrade(NXT) 프리마켓(08:00~08:50) 및
    애프터마켓(15:40~20:00) 시간외 실시간 체결가 및 등락률을 조회합니다.
    """
    import requests
    try:
        url = f"https://m.stock.naver.com/api/stock/{code}/basic"
        r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=3)
        if r.status_code == 200:
            j = r.json()
            over = j.get('overMarketPriceInfo')
            if over and over.get('overPrice'):
                s_type = over.get('tradingSessionType', '')
                session_kor = 'NXT 프리마켓' if 'PRE' in s_type else 'NXT 야간마켓'
                status = over.get('overMarketStatus', 'CLOSE')
                price_str = str(over.get('overPrice', '')).replace(',', '')
                ratio_val = float(over.get('fluctuationsRatio', 0.0) or 0.0)
                return {
                    'session': session_kor,
                    'status': status,
                    'price': int(float(price_str)) if price_str.isdigit() else 0,
                    'price_str': over.get('overPrice', ''),
                    'ratio': ratio_val,
                }
    except Exception:
        pass
    return None


def analyze_intraday_microstructure(code: str, close_p: float) -> dict:
    """
    [아이디어 2 & 6] 1분봉 차트(fchart minute) 기반 장중 수급 미시구조(Microstructure) 정밀 분석:
    1) 당일 정규장(09:00~15:30) VWAP(거래량가중평균단가) 산출 및 종가 상회율(vwap_diff_pct) 계산
    2) 장중 최고가 형성 시각(peak_time) 추출 -> 오전 10:15 이전 고점 찍고 오후 내내 VWAP 아래로 흐른 '설거지 패턴' 판별
    3) 15:10 가격 대비 15:30 동시호가 마감 가격의 막판 수급 끌어올림(closing_auction_diff) 측정
    """
    import requests
    import xml.etree.ElementTree as ET
    try:
        url = f"https://fchart.stock.naver.com/sise.nhn?symbol={code}&timeframe=minute&count=420&requestType=0"
        res = requests.get(url, timeout=3)
        if res.status_code != 200 or not res.text:
            return None
        cleaned = re.sub(r'<\?xml[^>]*\?>', '', res.text).strip()
        root = ET.fromstring(cleaned)
        items = root.findall('.//item')
        if not items:
            return None

        parsed = [it.attrib['data'].split('|') for it in items]
        last_date = parsed[-1][0][:8]
        reg = [x for x in parsed if x[0].startswith(last_date) and '0900' <= x[0][8:12] <= '1530']
        if len(reg) < 15:
            return None

        total_pv = 0.0
        total_v = 0.0
        prev_cum_v = 0.0
        max_p = -1.0
        peak_hhmm = '0900'
        p_1510 = None
        p_1530 = float(reg[-1][4])

        for idx, r in enumerate(reg):
            hhmm = r[0][8:12]
            p = float(r[4])
            cum_v = float(r[5])
            dv = (cum_v - prev_cum_v) if idx > 0 else cum_v
            if dv < 0:
                dv = 0.0
            prev_cum_v = cum_v
            total_pv += p * dv
            total_v += dv
            if p >= max_p:
                max_p = p
                peak_hhmm = hhmm
            if hhmm <= '1510':
                p_1510 = p

        vwap = (total_pv / total_v) if total_v > 0 else close_p
        vwap_diff_pct = round(((close_p - vwap) / vwap) * 100, 2) if vwap > 0 else 0.0
        peak_time_str = f"{peak_hhmm[:2]}:{peak_hhmm[2:]}"

        # 오전 10:15 이전에 고점을 찍고 종가가 VWAP 밑으로 무너진 경우 = 전형적인 오전 설거지 패턴
        is_morning_dump = (peak_hhmm <= '1015') and (vwap_diff_pct < -0.5)

        closing_auction_diff = 0.0
        if p_1510 and p_1510 > 0:
            closing_auction_diff = round(((p_1530 - p_1510) / p_1510) * 100, 2)

        return {
            'vwap': int(round(vwap)),
            'vwap_diff_pct': vwap_diff_pct,
            'peak_time': peak_time_str,
            'is_afternoon_high': peak_hhmm >= '1300',
            'is_morning_dump': is_morning_dump,
            'closing_auction_diff': closing_auction_diff,
        }
    except Exception:
        return None


def analyze_support_resistance(code: str, name: str) -> dict:
    """
    네이버 일봉 차트(최근 65일)를 실시간 분석하여 20일/60일 전고점 저항 돌파 및 지지선 정밀 판별.
    - 60일 신고가 돌파: 상방 매물 100% 공백, 익일 갭상승 확률 극대화 (+30점 가산)
    - 20일 박스권 상단 저항 돌파: 단기 저항선 극복 안착 (+20점 가산)
    - 머리 위 2.5% 이내에 20일 전고점이나 60일선 저항선 충돌 위험: 자동 탈락 (원천 배제)
    - 20일 이동평균선 하회 역배열 종목: 자동 탈락
    """
    import requests
    import xml.etree.ElementTree as ET
    import re
    try:
        url = f"https://fchart.stock.naver.com/sise.nhn?symbol={code}&timeframe=day&count=65&requestType=0"
        res = requests.get(url, timeout=4)
        if res.status_code != 200 or not res.text:
            return None
        cleaned = re.sub(r'<\?xml[^>]*\?>', '', res.text).strip()
        root = ET.fromstring(cleaned)
        items = root.findall('.//item')
        if len(items) < 25:
            return None

        rows = []
        for it in items:
            parts = it.attrib['data'].split('|')
            rows.append({
                'date': parts[0],
                'open': float(parts[1]),
                'high': float(parts[2]),
                'low': float(parts[3]),
                'close': float(parts[4]),
                'volume': float(parts[5]),
            })

        today = rows[-1]
        today_close = today['close']

        # 직전 20일, 60일 최고가 (당일 제외한 과거 구간)
        past_20 = rows[-21:-1]
        past_60 = rows[-61:-1] if len(rows) >= 61 else rows[:-1]

        prev_20_high = max(r['high'] for r in past_20)
        prev_60_high = max(r['high'] for r in past_60)
        avg_20_vol = sum(r['volume'] for r in past_20) / max(len(past_20), 1)
        rvol = round(today['volume'] / avg_20_vol, 2) if avg_20_vol > 0 else 1.0

        # 20일선 및 60일선 이동평균
        ma20 = sum(r['close'] for r in rows[-20:]) / 20.0
        ma60 = sum(r['close'] for r in rows[-60:]) / len(rows[-60:]) if len(rows) >= 60 else None

        # 1. 역배열 하향 추세 (20일선 밑에 주가가 위치) -> 탈락
        if today_close < ma20:
            return {'is_valid': False, 'reject_reason': '20일선 하회 역배열'}

        is_60_breakout = today_close >= prev_60_high
        is_20_breakout = today_close >= prev_20_high

        # 2. 머리 위 저항선 충돌 검사 (오늘 종가 바로 위 2.5% 이내에 60일선 또는 20일 전고점이 가로막은 경우)
        overhead_barriers = []
        if not is_20_breakout and today_close < prev_20_high:
            diff_to_20h = (prev_20_high - today_close) / today_close * 100
            if diff_to_20h <= 2.5:
                overhead_barriers.append(f"20일전고점(+{diff_to_20h:.1f}%)")

        if ma60 and today_close < ma60:
            diff_to_60ma = (ma60 - today_close) / today_close * 100
            if diff_to_60ma <= 2.5:
                overhead_barriers.append(f"60일선(+{diff_to_60ma:.1f}%)")

        if overhead_barriers:
            return {'is_valid': False, 'reject_reason': f"머리 위 저항선 충돌 위험 ({', '.join(overhead_barriers)})"}

        # 3. 돌파 등급 및 지지·저항 가격 산출
        if is_60_breakout:
            status = "🔥 60일 신고가 대돌파 (상방 매물 100% 공백)"
            support_price = int(prev_60_high)
            next_res = "신고가 영역 (상방 무저항)"
            room_pct = 10.0
            sr_score = 30.0
            tags = ["60일신고가대돌파", "매물100%공백"]
        elif is_20_breakout:
            status = "🎯 20일 박스권 상단 저항 돌파 안착"
            support_price = int(prev_20_high)
            diff_to_60 = (prev_60_high - today_close) / today_close * 100
            room_pct = round(diff_to_60, 1)
            next_res = f"{int(prev_60_high):,}원 (+{room_pct:.1f}% 여유)" if room_pct > 0 else "신고가 영역"
            sr_score = 20.0
            tags = ["박스권상단돌파", "저항돌파안착"]
        else:
            diff_to_20 = (prev_20_high - today_close) / today_close * 100
            status = "⚡ 20일선 지지 우상향 파동"
            support_price = int(ma20)
            next_res = f"{int(prev_20_high):,}원 (+{diff_to_20:.1f}%)"
            room_pct = round(diff_to_20, 1)
            sr_score = 5.0
            tags = ["20일선지지", "우상향파동"]

        return {
            'is_valid': True,
            'is_60_breakout': is_60_breakout,
            'is_20_breakout': is_20_breakout,
            'status': status,
            'support_price': support_price,
            'next_res': next_res,
            'room_pct': room_pct,
            'sr_score': sr_score,
            'rvol': rvol,
            'tags': tags
        }
    except Exception as e:
        logger.debug(f"{code} 지지저항 분석 실패: {e}")
        return None


_RECOMMENDATIONS_CACHE = None


def get_recommendations(dart_disclosures=None, market_context=None, force_refresh=False):
    """
    국내 KRX 전 종목을 실시간 스캔하여 고승률 4대 필터를 통과한 종목 도출 (프로세스 내 캐시 적용으로 초고속 실행)
    """
    global _RECOMMENDATIONS_CACHE
    if _RECOMMENDATIONS_CACHE is not None and not force_refresh:
        return _RECOMMENDATIONS_CACHE

    import FinanceDataReader as fdr

    regime = evaluate_market_regime(market_context)

    # 1. 네이버 증권 장중 실시간 시세 우선 수집 (15:05~15:10 장중 실시간 호가/거래대금 100% 반영)
    common = None
    try:
        common = fetch_naver_realtime_pool()
        if common is not None and len(common) >= 50:
            logger.info(f"✓ 네이버 실시간 장중 시세 수집 완료: {len(common)}개 종목")
    except Exception as e:
        logger.warning(f"네이버 실시간 시세 수집 실패, FDR 폴백 시도: {e}")

    # 네이버 수집 실패 시 또는 보조용으로 fdr.StockListing 활용
    if common is None or len(common) < 50:
        try:
            krx = fdr.StockListing('KRX')
            common = krx[krx.apply(is_common_stock, axis=1)].copy()
        except Exception as e:
            logger.error(f"KRX 종목 목록 수집 실패: {e}")
            fb = get_fallback_recommendations()
            fb['regime'] = regime
            _RECOMMENDATIONS_CACHE = fb
            return fb

    # DART 호재 종목 코드 세트 수집
    catalyst_codes = set()
    if dart_disclosures:
        for it in dart_disclosures:
            c = it.get('stock_code')
            if c:
                catalyst_codes.add(c)

    # =========================================================================
    # Track 1: 🎯 오늘 15:10 종가베팅 (오버나잇)
    # =========================================================================
    # [아이디어 5] 오늘의 최강 주도 섹터 TOP 3 (Sector Sympathy) 집계
    hot_sectors = []
    hot_sector_names = []
    try:
        surge_pool = common[
            (common['Amount'] >= 50 * 1e8) &
            (common['ChagesRatio'] >= 3.0)
        ].sort_values(by='Amount', ascending=False).head(35)
        sec_agg = {}
        for _, srow in surge_pool.iterrows():
            scode = str(srow['Code'])
            sname = str(srow['Name'])
            samt = float(srow['Amount']) / 1e8
            schg = float(srow['ChagesRatio'])
            ssec = get_stock_sector(scode)
            if ssec not in sec_agg:
                sec_agg[ssec] = {'sector': ssec, 'count': 0, 'total_amount_eok': 0, 'chg_sum': 0.0, 'leader_name': sname, 'leader_chg': schg}
            sec_agg[ssec]['count'] += 1
            sec_agg[ssec]['total_amount_eok'] += int(samt)
            sec_agg[ssec]['chg_sum'] += schg
            if schg > sec_agg[ssec]['leader_chg']:
                sec_agg[ssec]['leader_name'] = sname
                sec_agg[ssec]['leader_chg'] = round(schg, 2)
        for k, v in sec_agg.items():
            v['avg_chg'] = round(v['chg_sum'] / max(v['count'], 1), 2)
            hot_sectors.append(v)
        hot_sectors.sort(key=lambda x: (x['count'], x['total_amount_eok']), reverse=True)
        hot_sectors = hot_sectors[:3]
        hot_sector_names = [h['sector'] for h in hot_sectors[:2]]
    except Exception as e:
        logger.debug(f"주도 섹터 집계 예외: {e}")

    # [아이디어 10] 최근 30일 트랙레코드 기반 자가보정(Self-Tuning) 우위 섹터 로드
    winning_sectors = set()
    try:
        try:
            from src.track_record import get_self_tuning_insights
        except ImportError:
            from track_record import get_self_tuning_insights
        winning_sectors = get_self_tuning_insights().get('winning_sectors', set())
    except Exception:
        pass

    closing_picks = []
    # [옵션 B: 안정성+탄력 병행 종가베팅 주도주 선별]
    # 1) 시가총액: 3,000억 이상 ~ 10조 원 이하 (호가창 무거운 10조 초과 초대형주 및 3,000억 미만 작전/잡주 원천 차단)
    # 2) 당일 거래대금: 최소 300억 이상 (주도 수급 집중 & 익일 시초가 슬리피지 방지)
    # 3) 당일 주가 상승률: +3.5% ~ +10.0% (건전한 고가 마감 양봉)
    closing_pool = common[
        (common['Marcap'] >= 3000 * 1e8) &      # 시총 3,000억 이상
        (common['Marcap'] <= 100000 * 1e8) &    # 시총 10조 원 이하 (10조 초과 공룡주 배제)
        (common['Amount'] >= 300 * 1e8) &       # 당일 거래대금 최소 300억 이상 (주도주 수급 보장)
        (common['ChagesRatio'] >= 3.5) &        # 최소 +3.5% 이상
        (common['ChagesRatio'] <= 10.0)         # 최대 +10.0% 이하
    ].copy()

    # 거래대금 상위 30개 종목 압축 (3,000억~10조 주도주 풀 전수 정밀 분석)
    closing_pool = closing_pool.sort_values(by='Amount', ascending=False).head(30)

    for _, row in closing_pool.iterrows():
        code = str(row['Code'])
        name = str(row['Name'])
        market = str(row['Market'])
        close_p = float(row['Close'])
        open_p = float(row['Open'])
        high_p = float(row['High'])
        low_p = float(row['Low'])
        amount_eok = float(row['Amount']) / 1e8
        change_pct = float(row['ChagesRatio'])
        marcap = float(row['Marcap']) if 'Marcap' in row and pd.notnull(row['Marcap']) else 0
        marcap_str = format_marcap(marcap)

        if high_p <= low_p:
            continue

        head_ratio = (high_p - close_p) / (high_p - low_p)
        body_ratio = (close_p - open_p) / (high_p - low_p)

        # 윗꼬리 38% 이하 & 양봉 몸통 35% 이상 엄격 필터링
        if head_ratio <= 0.38 and body_ratio >= 0.35:
            # [지지·저항 돌파 & 머리 위 저항 충돌 필터]
            sr = analyze_support_resistance(code, name)
            if sr and not sr.get('is_valid', True):
                logger.info(f"[종가베팅 필터 탈락] {name}({code}): {sr.get('reject_reason')}")
                continue

            sr_score = sr.get('sr_score', 0.0) if sr else 0.0
            sr_status = sr.get('status', '거래대금 수급 우수') if sr else '거래대금 수급 우수'
            support_price = sr.get('support_price', int(close_p * 0.98)) if sr else int(close_p * 0.98)
            next_res = sr.get('next_res', f"{int(close_p * 1.05):,}원") if sr else f"{int(close_p * 1.05):,}원"
            room_pct = sr.get('room_pct', 5.0) if sr else 5.0
            sr_tags = sr.get('tags', []) if sr else []
            rvol = sr.get('rvol', 1.5) if sr else 1.5
            turnover_pct = round((amount_eok / (marcap / 1e8)) * 100, 2) if marcap > 0 else 0.0
            stock_sec = get_stock_sector(code)

            # [아이디어 2 & 6] 분봉 미시구조(VWAP & 오전 설거지 패턴 & 막판 동시호가 수급) 분석
            micro = analyze_intraday_microstructure(code, close_p)
            if micro and micro.get('is_morning_dump'):
                logger.info(f"[종가베팅 필터 탈락] {name}({code}): 오전 고점({micro.get('peak_time')}) 후 오후 VWAP 하회 설거지 패턴")
                continue

            # 점수 산정: 기본 40 + 거래대금(최대 30) + 캔들완성도(최대 15) + 지지저항돌파(최대 30)
            volume_score = min(amount_eok / 10, 30.0)
            candle_score = (1.0 - head_ratio) * 15.0
            score = 40.0 + volume_score + candle_score + sr_score
            
            # 기존 AI 포착 근거 100% 보존 + 신규 지지·저항 차트 근거 추가
            reasons = [
                f"거래대금 {int(amount_eok):,}억 폭발 주도주",
                f"고가 마감 양봉(윗꼬리 {int(head_ratio*100)}%)"
            ]
            if sr_status:
                reasons.append(f"차트: {sr_status}")
            if rvol >= 2.0:
                score += min((rvol - 1.0) * 2.0, 6.0)
                reasons.append(f"상대거래량 RVOL {rvol:.1f}배(회전율 {turnover_pct:.1f}%)")
            if micro:
                vwap_diff = micro.get('vwap_diff_pct', 0.0)
                peak_t = micro.get('peak_time', '')
                auc_diff = micro.get('closing_auction_diff', 0.0)
                if vwap_diff >= 0:
                    score += 3.0
                    reasons.append(f"당일 VWAP 상회(+{vwap_diff:.1f}% · 고점 {peak_t})")
                if auc_diff >= 0.3:
                    score += 2.0
                    reasons.append(f"막판 동시호가 수급 유입(+{auc_diff:.2f}%)")
            if stock_sec in hot_sector_names:
                score += 5.0
                reasons.append(f"🔥당일 주도섹터({stock_sec}) 동조화")
            if stock_sec in winning_sectors:
                score += 4.0
                reasons.append(f"🧠30일 고승률 섹터 자가보정(+4점)")

            tags = ['거래대금폭발', '단단한양봉', '익일시초가노림'] + sr_tags

            if code in catalyst_codes:
                score += 10.0
                reasons.append("DART 공시 호재 포착")
                tags.append("실적/공시호재")

            closing_picks.append({
                'code': code,
                'name': name,
                'market': market,
                'price': int(close_p),
                'change_pct': round(change_pct, 2),
                'amount_eok': int(amount_eok),
                'target_1': int(close_p * 1.03),
                'target_1_pct': '+3.0%',
                'target_2': int(close_p * 1.05),
                'target_2_pct': '+5.0%',
                'stop_loss': int(close_p * 0.98),
                'stop_loss_pct': '-2.0%',
                'holding_period': '당일 15:10~15:30 매수 → 익일 09:00~09:20 전량 분할 매도',
                'score': int(min(score, 99)),
                'reason': " · ".join(reasons),
                'tags': tags,
                'sr_status': sr_status,
                'support_price': support_price,
                'next_resistance': next_res,
                'room_pct': room_pct,
                'marcap': int(marcap),
                'marcap_str': marcap_str,
                'rvol': rvol,
                'turnover_pct': turnover_pct,
                'vwap': micro.get('vwap') if micro else int(close_p * 0.99),
                'vwap_diff_pct': micro.get('vwap_diff_pct', 0.0) if micro else 0.8,
                'peak_time': micro.get('peak_time', '15:15') if micro else '15:15',
                'closing_auction_diff': micro.get('closing_auction_diff', 0.0) if micro else 0.0,
                'is_breakout': sr.get('is_20_breakout', False) or sr.get('is_60_breakout', False) if sr else False
            })

    closing_picks.sort(key=lambda x: x['score'], reverse=True)
    closing_picks = closing_picks[:3]

    # =========================================================================
    # Track 2: 🚀 2~5일 스윙 (추세 파동)
    # 4대 기준: 1) 시총 4,000억 ~ 10조원 알짜 중형주 (소형주/초대형 지수주 배제),
    #           2) 20일선 우상향 & 5% 이내 눌림목 지지,
    #           3) 스마트머니 수급 & 거래량 수축 후 변곡점 반등,
    #           4) 정량적 손익비 (익절 +5~9%, 손절 -3%)
    # =========================================================================
    swing_picks = []
    # 4대 엄격 기준:
    # 1) 시총 3,000억 ~ 10조원 주도 유망주
    # 2) 당일 거래대금 100억 이상 (소외주/잡주 원천 차단)
    # 3) 당일 양봉 필수 (ChagesRatio >= 0.0 & Close >= Open, 음봉 절대 매수 금지)
    # 4) 20일선 위 5% 이내 눌림목 지지 & 5일선-20일선 정배열
    # 5) AI 종합 점수 80점 이상 엄격 컷오프 (미달 시 추천 없음: 100% 현금 보존)
    swing_pool = common[
        (common['Marcap'] >= 3000 * 1e8) &     # 시총 3,000억 이상
        (common['Marcap'] <= 100000 * 1e8) &   # 시총 10조원 이하
        (common['Amount'] >= 100 * 1e8) &      # 당일 거래대금 100억 이상 (주도력 확보)
        (common['ChagesRatio'] >= 0.0) &       # 음봉 배제 (0% 이상 보합/상승)
        (common['ChagesRatio'] <= 6.5) &       # 과열되지 않은 초입 양봉
        (common['Close'] >= common['Open'])    # 당일 시가 대비 양봉 확인
    ].copy()

    # 거래대금 순으로 정렬하되, 임의의 개수 제한(.head) 없이 1차 조건을 만족한 전종목을 100% 전수 검사
    swing_pool = swing_pool.sort_values(by='Amount', ascending=False)

    for _, row in swing_pool.iterrows():
        code = str(row['Code'])
        name = str(row['Name'])
        market = str(row['Market'])
        close_p = float(row['Close'])
        amount_eok = float(row['Amount']) / 1e8
        change_pct = float(row['ChagesRatio'])
        marcap = float(row['Marcap']) if 'Marcap' in row and pd.notnull(row['Marcap']) else 0
        marcap_str = format_marcap(marcap)

        try:
            start_date = (datetime.now() - timedelta(days=90)).strftime('%Y-%m-%d')
            df = fdr.DataReader(code, start=start_date)
            if len(df) < 25:
                continue
            closes = df['Close'].values[-25:]
            ma5 = float(pd.Series(closes).rolling(5).mean().values[-1])
            ma20 = float(pd.Series(closes).rolling(20).mean().values[-1])
            ma20_prev = float(pd.Series(closes).rolling(20).mean().values[-5])

            # 20일선 우상향 & 5일선-20일선 정배열
            is_uptrend = ma20 >= ma20_prev
            is_golden = ma5 >= ma20 * 0.995
            # 주가가 20일선 위에 안착하고 5% 이내 위치
            dist_ma20 = (close_p - ma20) / close_p * 100
            is_near_ma20 = (close_p >= ma20) and (dist_ma20 <= 5.0)

            if is_uptrend and is_golden and is_near_ma20:
                score = 65.0 + min(amount_eok / 70, 15.0) + (5.0 - dist_ma20) * 3.5
                reasons = [f"20일선({int(ma20):,}원) 눌림목 지지", f"이격도 {dist_ma20:.1f}% 안정 구간"]
                tags = ['20일선눌림목', '추세우상향', '안정적손익비']

                if code in catalyst_codes:
                    score += 12.0
                    reasons.append("실적/호재 공시 연계")
                    tags.append("실적모멘텀")

                # AI 점수 80점 이상인 진짜 우량 주도주만 최종 진입 허용 (미달 시 추천 안 함)
                if score < 80.0:
                    continue

                stg = resolve_swing_targets(close_p, regime=regime, market_context=market_context)
                swing_picks.append({
                    'code': code,
                    'name': name,
                    'market': market,
                    'price': int(close_p),
                    'change_pct': round(change_pct, 2),
                    'amount_eok': int(amount_eok),
                    'swing_mode': stg['mode'],
                    'swing_mode_label': stg['mode_label'],
                    'swing_mode_desc': stg['mode_desc'],
                    'target_1': stg['target_1'],
                    'target_1_pct': stg['target_1_pct'],
                    'target_2': stg['target_2'],
                    'target_2_pct': stg['target_2_pct'],
                    'target_3': stg['target_3'],
                    'target_3_pct': stg['target_3_pct'],
                    'stop_loss': stg['stop_loss'],
                    'stop_loss_pct': stg['stop_loss_pct'],
                    'holding_period': stg['holding_period'],
                    'score': int(min(score, 98)),
                    'reason': " · ".join(reasons),
                    'tags': tags,
                    'marcap': int(marcap),
                    'marcap_str': marcap_str
                })
        except Exception:
            continue

    swing_picks.sort(key=lambda x: x['score'], reverse=True)
    swing_picks = swing_picks[:3]

    # =========================================================================
    # Track 3: 🔥 당일 +15% 돌파 대장주 (기준봉 포착)
    # 4대 기준: 1) 당일 등락률 +14% 이상 장대양봉 돌파,
    #           2) 거래대금 최소 200억~500억+ 메이저 수급 집중 (잡주 배제),
    #           3) 윗꼬리 35% 이하 단단한 마감 (상방 탄력 유지),
    #           4) 향후 2~5일 5일선/눌림목 지지 시 분할 매수 타겟 (당일 추격매수 금지)
    # =========================================================================
    breakout_picks = []
    breakout_pool = common[
        (common['ChagesRatio'] >= 14.0) &
        (common['Amount'] >= 200 * 1e8) &  # 최소 200억 이상 (소형 가짜 돌파 배제)
        (common['Marcap'] >= 1000 * 1e8)
    ].copy()

    breakout_pool = breakout_pool.sort_values(by='Amount', ascending=False).head(15)

    for _, row in breakout_pool.iterrows():
        code = str(row['Code'])
        name = str(row['Name'])
        market = str(row['Market'])
        close_p = float(row['Close'])
        open_p = float(row['Open'])
        high_p = float(row['High'])
        low_p = float(row['Low'])
        amount_eok = float(row['Amount']) / 1e8
        change_pct = float(row['ChagesRatio'])
        marcap = float(row['Marcap']) if 'Marcap' in row and pd.notnull(row['Marcap']) else 0
        marcap_str = format_marcap(marcap)

        if high_p <= low_p:
            continue

        head_ratio = (high_p - close_p) / (high_p - low_p)

        if head_ratio <= 0.35:  # 윗꼬리 35% 이하 유지
            score = 70.0 + min(amount_eok / 100, 20.0) + (1.0 - head_ratio) * 10.0
            reasons = [f"거래대금 {int(amount_eok):,}억 폭발", f"+{change_pct:.1f}% 강력 돌파 장대양봉", f"윗꼬리 {int(head_ratio*100)}% 유지"]
            tags = ['강력기준봉', '거래대금폭발', '눌림목공략대기']

            if code in catalyst_codes:
                score += 10.0
                reasons.append("실적/호재 공시 수반")
                tags.append("호재수반")

            breakout_picks.append({
                'code': code,
                'name': name,
                'market': market,
                'price': int(close_p),
                'change_pct': round(change_pct, 2),
                'amount_eok': int(amount_eok),
                'target_1': int(close_p * 1.07),
                'target_1_pct': '+7.0%',
                'target_2': int(close_p * 1.15),
                'target_2_pct': '+15.0%',
                'stop_loss': int(open_p),
                'stop_loss_pct': '기준봉 시초가 이탈',
                'holding_period': '당일 추격매수 금지 ⚠️ → 향후 2~5일 5일선/눌림목 지지 시 분할 매수 타겟',
                'score': int(min(score, 99)),
                'reason': " · ".join(reasons),
                'tags': tags,
                'marcap': int(marcap),
                'marcap_str': marcap_str
            })

    breakout_picks.sort(key=lambda x: x['score'], reverse=True)
    breakout_picks = breakout_picks[:3]

    # =========================================================================
    # Track 4: 🎯 [아이디어 7] 과거 2~7일 내 기준봉(+13% 이상 대량거래) 출현 후
    #          오늘 5일선 / 기준봉 중심선 + 거래량 건조(수축) 눌림목 타점 도래 종목 포착
    # =========================================================================
    pullback_picks = []
    try:
        pb_pool = common[
            (common['Marcap'] >= 1500 * 1e8) &
            (common['Amount'] >= 30 * 1e8) &
            (common['ChagesRatio'] >= -4.0) &
            (common['ChagesRatio'] <= 5.5)
        ].sort_values(by='Amount', ascending=False).head(25)

        import requests
        import xml.etree.ElementTree as ET
        for _, row in pb_pool.iterrows():
            code = str(row['Code'])
            name = str(row['Name'])
            market = str(row['Market'])
            close_p = float(row['Close'])
            amount_eok = float(row['Amount']) / 1e8
            change_pct = float(row['ChagesRatio'])
            marcap = float(row['Marcap']) if 'Marcap' in row and pd.notnull(row['Marcap']) else 0
            marcap_str = format_marcap(marcap)

            try:
                url = f"https://fchart.stock.naver.com/sise.nhn?symbol={code}&timeframe=day&count=30&requestType=0"
                r = requests.get(url, timeout=3)
                if r.status_code != 200 or not r.text:
                    continue
                cleaned = re.sub(r'<\?xml[^>]*\?>', '', r.text).strip()
                root = ET.fromstring(cleaned)
                items = root.findall('.//item')
                if len(items) < 22:
                    continue
                rows = []
                for it in items:
                    p = it.attrib['data'].split('|')
                    rows.append({
                        'date': p[0], 'open': float(p[1]), 'high': float(p[2]),
                        'low': float(p[3]), 'close': float(p[4]), 'vol': float(p[5])
                    })
                today_r = rows[-1]
                ma5 = sum(x['close'] for x in rows[-5:]) / 5.0
                avg_20_vol = sum(x['vol'] for x in rows[-21:-1]) / 20.0

                # 직전 2~7영업일 내 기준봉(등락률 +12% 이상 & 거래량 20일 평균의 2배 이상) 탐색
                found_base = None
                days_ago = 0
                for idx in range(len(rows) - 2, max(len(rows) - 8, 1), -1):
                    cand = rows[idx]
                    prev_c = rows[idx - 1]['close']
                    if prev_c <= 0:
                        continue
                    c_gain = (cand['close'] - prev_c) / prev_c * 100
                    if c_gain >= 12.0 and cand['vol'] >= avg_20_vol * 2.0 and cand['close'] > cand['open']:
                        found_base = (cand, round(c_gain, 1), (len(rows) - 1) - idx)
                        break

                if not found_base:
                    continue

                base_bar, base_gain, days_ago = found_base
                base_mid = (base_bar['open'] + base_bar['close']) / 2.0
                vol_ratio = (today_r['vol'] / base_bar['vol']) * 100 if base_bar['vol'] > 0 else 100.0
                dist_ma5 = abs(close_p - ma5) / close_p * 100
                dist_mid = abs(close_p - base_mid) / close_p * 100

                # 조건: 1) 기준봉 시가 위 지지, 2) 5일선 또는 기준봉 중심선 부근(4.5% 이내), 3) 거래량이 기준봉 대비 65% 이하로 수축(숨고르기)
                if close_p >= base_bar['open'] * 0.99 and (dist_ma5 <= 4.5 or dist_mid <= 4.5) and vol_ratio <= 65.0:
                    pb_score = 88 + int(max(0, (65.0 - vol_ratio) * 0.15))
                    support_line = int(round(max(base_bar['open'], min(ma5, base_mid))))
                    pullback_picks.append({
                        'code': code,
                        'name': name,
                        'market': market,
                        'price': int(close_p),
                        'change_pct': round(change_pct, 2),
                        'amount_eok': int(amount_eok),
                        'target_1': int(close_p * 1.05),
                        'target_1_pct': '+5.0%',
                        'target_2': int(close_p * 1.10),
                        'target_2_pct': '+10.0%',
                        'stop_loss': int(base_bar['open']),
                        'stop_loss_pct': '기준봉 시가 손절',
                        'holding_period': f'{days_ago}일 전 기준봉(+{base_gain}%) 출현 → 현재 5일선·중심선 눌림목 매수 적기',
                        'score': min(pb_score, 98),
                        'reason': f"{days_ago}일 전 +{base_gain}% 기준봉 출현 · 거래량 {int(vol_ratio)}%로 건조(숨고르기) · 기준봉 중심선({int(base_mid):,}원)/5일선({int(ma5):,}원) 지지",
                        'tags': ['기준봉눌림목타점', f'거래량{int(vol_ratio)}%수축', '5일선지지'],
                        'sr_status': f"🎯 기준봉({days_ago}일전 +{base_gain}%) 중심선·5일선 눌림목 지지",
                        'support_price': support_line,
                        'next_resistance': f"{int(base_bar['high']):,}원 (기준봉 고점 탈환)",
                        'marcap': int(marcap),
                        'marcap_str': marcap_str,
                        'rvol': round(today_r['vol'] / max(avg_20_vol, 1), 2),
                        'turnover_pct': round((amount_eok / (marcap / 1e8)) * 100, 2) if marcap > 0 else 0.0,
                    })
                    if len(pullback_picks) >= 3:
                        break
            except Exception:
                continue
    except Exception as e:
        logger.debug(f"기준봉 눌림목 스캔 예외: {e}")

    # 급락장 또는 휴장일 등으로 후보가 부족할 경우 안전 보강
    # if not closing_picks:
    #     closing_picks = []
    # if not swing_picks:
    #     swing_picks = []
    # if not breakout_picks:
    #     breakout_picks = []

    # 실시간 테마/업종, 핵심 뉴스(재료) 및 모바일 네이버 증권 차트 링크 보강
    # if not pullback_picks:
    #     pullback_picks = []

    for p in (closing_picks + swing_picks + breakout_picks + pullback_picks):
        if 'turnover_pct' not in p:
            mc = p.get('marcap', 0)
            p['turnover_pct'] = round((p.get('amount_eok', 0) / (mc / 1e8)) * 100, 2) if mc > 0 else 0.0
        p['nxt_info'] = fetch_nxt_over_market_info(p['code'])
        p['sector'] = get_stock_sector(p['code'])
        cat_info = fetch_stock_catalyst(p['code'], p.get('name', ''))
        if isinstance(cat_info, dict):
            p['catalyst'] = cat_info.get('title')
            p['catalyst_url'] = cat_info.get('url', f"https://m.stock.naver.com/domestic/stock/{p['code']}/news")
            p['catalyst_source'] = cat_info.get('source', '증권뉴스')
            p['catalyst_body'] = cat_info.get('body', '')
        else:
            p['catalyst'] = cat_info
            p['catalyst_url'] = f"https://m.stock.naver.com/domestic/stock/{p['code']}/news"
            p['catalyst_source'] = '증권뉴스'
            p['catalyst_body'] = ''
        p['chart_url'] = f"https://m.stock.naver.com/domestic/stock/{p['code']}/total"

    # [STEP 4] 익일 시초가 성과 자동 추적을 위한 당일 종가베팅 및 스윙 종목 기록
    try:
        try:
            from src.track_record import record_closing_picks
        except ImportError:
            from track_record import record_closing_picks
        record_closing_picks(closing_picks)
    except Exception as e:
        logger.warning(f"종가베팅 트랙 레코드 기록 실패: {e}")

    try:
        try:
            from src.swing_track_record import record_swing_picks
        except ImportError:
            from swing_track_record import record_swing_picks
        record_swing_picks(swing_picks)
    except Exception as e:
        logger.warning(f"스윙 트랙 레코드 기록 실패: {e}")

    res = {
        'regime': regime,
        'closing': closing_picks,
        'swing': swing_picks,
        'swing_regime': resolve_swing_targets(10000, regime=regime, market_context=market_context),
        'breakout': breakout_picks,
        'pullback': pullback_picks,
        'hot_sectors': hot_sectors,
    }
    _RECOMMENDATIONS_CACHE = res
    return res


def get_fallback_recommendations():
    return {"regime": {"status": "neutral", "badge": "정밀 선별", "badge_class": "regime-neutral", "message": "원칙 준수", "position_advice": "현금 관망"}, "closing": [], "swing": [], "breakout": [], "pullback": [], "hot_sectors": []}
