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
from concurrent.futures import ThreadPoolExecutor, as_completed
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


_CATALYST_CACHE = {}

# ─── 전 종목 5단계(S+ / S / A / B / C / F) 뉴스·공시 정밀 키워드 사전 ───
_F_TIER_NEGATIVE_KEYWORDS = (
    '어닝 쇼크', '어닝쇼크', '컨센서스 하회', '기대치 하회', '예상치 하회',
    '적자전환', '적자지속', '적자확대', '영업적자', '당기순적자', '영업손실', '순손실', '평가손실', '직격탄',
    '영업익 감소', '영업이익 감소', '역성장', '실적 부진', '매출 감소', '가이던스 하향',
    '목표가 하향', '목표주가 하향', '목표가↓', '목표주가↓',
    '계약 해지', '계약해지', '공급계약 해지', '단일판매해지',
    '압박 우려', '압박', '노조', '파업', '소송', '피소', '고발', '압수수색',
    '횡령', '배임', '불발', '무산', '철회', '차질', '논란', '엇갈린',
    '급락', '하락세', '리콜', '가동 중단', '납품 지연',
    '임상 실패', '임상 중단', '보완요구', 'CRL',
    '유상증자', '전환사채', '전환청구권', '신주인수권', '교환사채', '추가상장',
    '감자결정', '무상감자', '자기주식처분', '자사주 처분', '블록딜', '시간외대량매매',
    '장내매도', '보호예수 해제', '락업 해제', '공매도 과열',
    '투자주의', '투자경고', '투자위험', '단기과열', '불성실공시', '관리종목', '감사의견 거절',
)
_F_TIER_NEG_REGEX = re.compile(
    r'(?:영업익|영업이익|순이익|매출|실적).{0,24}?(?:\d+(?:\.\d+)?%\s*↓|감소|급감|하락|반토막|축소)'
    r'|(?:단일판매|공급계약|수주|합병|인수).{0,24}?(?:해지|취소|철회|무산|연기|지연|축소)'
    r'|\d+(?:\.\d+)?억\s*적자|적자(?!\s*(?:탈출|축소|개선|해소))'
)

_S_PLUS_KEYWORDS = (
    '단일판매', '공급계약체결', '공급계약 체결', '공사수주',
    '주식소각결정', '주식 소각 결정', '자사주 소각', '소각결정', '공개매수', '무상증자결정',
    '어닝 서프라이즈', '어닝서프라이즈', '흑자전환', '사상 최대', '역대 최대',
    'FDA 승인', 'FDA 최종', '품목허가 승인', '품목허가 획득', 'EMA 승인',
    '기술수출 본계약', '퀄테스트 통과', '퀄테스트 최종 통과',
)
_S_PLUS_SURGE_REGEX = re.compile(
    r'(?:영업익|영업이익|순이익).{0,28}?(?:[1-9]\d{2,}(?:\.\d+)?%\s*(?:↑|증가|급증|폭증)|폭증)'
)

_S_TIER_KEYWORDS = (
    '수주 잭팟', '대규모 수주', '수주 급증', '공급 계약', '공급계약', '장기공급', '독점 공급',
    '본계약', '우선협상대상자', '양산 개시', '납품 시작', '초도물량', '확정발주', '완판',
    '신규시설투자', '컨센서스 상회', '기대치 상회', '턴어라운드', '가이던스 상향',
    '자기주식취득결정', '자사주 취득', '자사주 매입', '배당 확대', '기업가치제고', '밸류업',
    '마일스톤 유입', '마일스톤 수령', '기술이전 계약', 'MSCI 편입', '코스피200 편입', '코스닥150 편입', '장내매수',
)
_S_TIER_EARNINGS_REGEX = re.compile(
    r'(?:영업익|영업이익).{0,28}?(?:\d+(?:\.\d+)?%\s*(?:↑|증가)|호실적)'
)

_A_TIER_KEYWORDS = (
    '목표가 상향', '목표주가 상향', '목표가↑', '목표주가↑', '비중확대', '최선호주', '탑픽', 'Top Pick', '커버리지 개시',
    'CAPA 증설', '공장 증설', '증설', '풀가동', '판가 인상', '국책과제', '시장점유율 1위', '국내 1위',
    '신작 흥행', '수출 호조', '신규 고객사', '관세 반사이익', '수주 확대', '공급 확대', '공급 호조', '납품',
)

_C_TIER_SOFT_HYPE_KEYWORDS = (
    '전시회 참가', '전시회 출품', '박람회 참가', '박람회', '학회 발표', '학회 참가', '포스터 발표', '초록 공개',
    '세미나', '간담회', '출시 예정', '기대감', 'MOU', '양해각서', 'LOI', '투자의향서',
    '추진', '검토', '타진', '인수설', '합병 추진', '우회상장',
    '임상 1상', '임상 2상', '임상 2a상', '임상 2b상', '임상 3상', '임상 진척', '전임상', '동물실험', '세포실험',
    '유치 나섰', '유치에 나섰', '본격 유치', '멤버십 제도', '멤버십 도입', '프로모션', '캠페인', '팝업스토어', '할인 행사', '이벤트 개최', '리뉴얼 오픈',
)


def classify_catalyst_impact(title: str, body: str = "", name: str = "", sector: str = "", code: str = "", is_disclosure: bool = False) -> dict:
    """
    뉴스·공시 텍스트를 5단계(S+ / S / A / B / C / F)로 정밀 판정하고 AI 점수 가감치(score_delta)를 반환합니다.
    - 악재 우선 판정(Negative-First Override): 해지/감소/우려/희석 키워드가 포함되면 호재 단어가 있어도 즉시 F급(-20점) 처리
    """
    text = f"{title or ''} {body or ''}".strip()
    title_str = str(title or '').strip()
    is_bio_or_holding = (
        code != '053800'
        and sector not in ('IT/SW', '반도체', '기계/장비', '전력/원전', '방산/우주', '조선/해운')
        and (
            '바이오' in sector or '제약' in sector
            or any(k in name for k in ('바이오', '제약', '파마', '테라퓨틱스', '생명', '홀딩스', '지주', '사이언스', '랩'))
        )
    )

    # 1순위: 🔴 F급 (악재·실적감소·계약해지·갈등·희석 — 최우선 차단)
    if any(fk in title_str for fk in _F_TIER_NEGATIVE_KEYWORDS) or _F_TIER_NEG_REGEX.search(title_str):
        return {
            'tier': 'F',
            'score_delta': -20.0,
            'tier_label': '🔴F급 악재·리스크 감지(-20점)',
            'has_hard_catalyst': False,
        }

    # 2순위: 🟢 S+급 (+15점 — 확정 수주공시·소각·어닝서프라이즈·FDA승인)
    has_s_plus = any(sk in title_str for sk in _S_PLUS_KEYWORDS) or bool(_S_PLUS_SURGE_REGEX.search(title_str))
    if is_disclosure and any(dk in title_str for dk in ('단일판매', '공급계약', '공사수주', '소각결정', '주식소각', '무상증자', '공개매수')):
        has_s_plus = True
    if has_s_plus:
        return {
            'tier': 'S+',
            'score_delta': 15.0,
            'tier_label': '🟢S+급 초특급 확정호재(+15점)',
            'has_hard_catalyst': True,
        }

    # 3순위: 🟢 S급 (+12점 — 수주·양산·턴어라운드·자사주취득·밸류업·마일스톤)
    has_s = any(sk in title_str for sk in _S_TIER_KEYWORDS) or bool(_S_TIER_EARNINGS_REGEX.search(title_str))
    if is_disclosure and any(dk in title_str for dk in ('자기주식취득', '신규시설투자', '기업가치제고', '잠정실적', '영업실적')):
        has_s = True
    if has_s:
        return {
            'tier': 'S',
            'score_delta': 12.0,
            'tier_label': '🟢S급 확정호재(+12점)',
            'has_hard_catalyst': True,
        }

    # 4순위: 🟡 C급 (-6점 / 바이오·홀딩스 -10점 — 확정 계약 없는 단순 행사·홍보·기대감·초기임상 재료소멸)
    if any(ck in text for ck in _C_TIER_SOFT_HYPE_KEYWORDS):
        penalty = -10.0 if is_bio_or_holding else -6.0
        return {
            'tier': 'C',
            'score_delta': penalty,
            'tier_label': f"🟡C급 단발·홍보·재료소멸 주의({int(penalty)}점)",
            'has_hard_catalyst': False,
        }

    # 5순위: 🔵 A급 (+6점 — 목표가 상향·증설·점유율 확대·수출 호조)
    if any(ak in title_str for ak in _A_TIER_KEYWORDS):
        return {
            'tier': 'A',
            'score_delta': 6.0,
            'tier_label': '🔵A급 성장·리포트 모멘텀(+6점)',
            'has_hard_catalyst': False,
        }

    # 6순위: ⚪ B급 (0점 ~ +2점 — 본업 직결 특징주 및 일반 수급 모멘텀)
    if '[특징주]' in title_str or any(bk in text for bk in ('수혜', '강세', '돌파', '신고가')):
        return {
            'tier': 'B',
            'score_delta': 2.0,
            'tier_label': '⚪B급 업종·수혜 모멘텀(+2점)',
            'has_hard_catalyst': False,
        }
    return {
        'tier': 'B',
        'score_delta': 0.0,
        'tier_label': '⚪B급 수급 모멘텀(0점)',
        'has_hard_catalyst': False,
    }


def fetch_stock_catalyst(code, name="", sector=""):
    """
    종목별 실제 핵심 상승 재료(호재 뉴스 및 DART 공시) 정밀 추출 및 5단계(S+/S/A/B/C/F) 스코어링 엔진.
    1) 단순 시황/지수 마감 기사 및 타 종목 기사 원천 배제 (제목에 해당 종목명/약칭 필수)
    2) DART 주요 경영 공시(단일판매공급계약, 주식소각, 신규시설투자 등) 교차 검증 및 해지/정정 역방향 필터링
    3) S+급(+15점) / S급(+12점) / A급(+6점) / B급(0~+2점) / C급(-6~-10점) / F급(-20점) 정량 판정 반환
    """
    cache_key = f"{code}:{name}:{sector}"
    if cache_key in _CATALYST_CACHE:
        return _CATALYST_CACHE[cache_key]

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
    elif '에스디에스' in short_name or 'SDS' in short_name:
        aliases.extend(['삼성SDS', '삼성에스디에스'])
    elif '씨엔에스' in short_name or 'CNS' in short_name:
        aliases.extend(['LG CNS', 'LG씨엔에스', '엘지씨엔에스'])

    # 1. DART 공시 우선 확인 (당일 기준: 직전 영업일 15:30 장마감 이후 ~ 오늘 발생한 신규 확정 호재 공시만 인정)
    now_kst = datetime.now(KST)
    today_ymd = now_kst.strftime('%Y%m%d')
    prev_bday_dt = now_kst - timedelta(days=1)
    while prev_bday_dt.weekday() >= 5:
        prev_bday_dt -= timedelta(days=1)
    prev_ymd = prev_bday_dt.strftime('%Y%m%d')

    def _is_today_fresh(raw_dt_str: str) -> bool:
        digits = re.sub(r'[^0-9]', '', str(raw_dt_str or ''))
        if len(digits) < 8:
            return False
        ymd, hm = digits[:8], (digits[8:12] if len(digits) >= 12 else '0900')
        return (ymd == today_ymd) or (ymd == prev_ymd and hm >= '1530')

    recent_3d_dates = {
        (now_kst - timedelta(days=offset)).strftime('%Y%m%d')
        for offset in range(4)
    }
    disc_info = None
    try:
        url_disc = f'https://m.stock.naver.com/api/stock/{code}/disclosure?pageSize=8&page=1'
        req_disc = urllib.request.Request(url_disc, headers=headers)
        with urllib.request.urlopen(req_disc, timeout=3) as resp:
            discs = json.loads(resp.read().decode('utf-8'))
            impact_keywords = [
                '단일판매', '공급계약', '공사수주', '주식소각', '소각결정', '자기주식취득',
                '신규시설투자', '기업가치제고', '무상증자', '공개매수', '잠정실적', '영업실적',
            ]
            bad_disc_words = ('해지', '취소', '철회', '기재정정', '자기주식처분', '유상증자', '전환사채', '전환청구권')
            for d in discs:
                title = d.get('title', '')
                raw_d_dt = d.get('datetime') or d.get('date') or d.get('regDt') or ''
                if any(bw in title for bw in bad_disc_words):
                    continue
                if '변경상장' in title:
                    # 변경상장(주식소각)은 사후 행정 완료 통보이므로 +15점 가산 없이 0점 참고 정보로만 보존 (최근 5일)
                    d_ymd = re.sub(r'[^0-9]', '', str(raw_d_dt))[:8]
                    if '주식소각' in title and d_ymd and d_ymd >= (now_kst - timedelta(days=5)).strftime('%Y%m%d'):
                        clean_d = re.sub(r'^\([^\)]+\)\s*', '', title)
                        clean_d = re.sub(r'^(주|\(주\)|주식회사)\s*', '', clean_d)
                        disc_info = {
                            'title': f"[공시·참고] {clean_d}",
                            'url': f"https://m.stock.naver.com/domestic/stock/{code}/disclosure",
                            'source': 'DART 전자공시',
                            'body': f"{name} 주식소각 변경상장 완료 공시 (사후 참고)",
                            'tier': 'B',
                            'score_delta': 0.0,
                            'tier_label': '⚪B급 소각완료 참고(0점)',
                            'has_hard_catalyst': False,
                        }
                        break
                    continue
                if not _is_today_fresh(raw_d_dt):
                    continue  # 당일(전일 장마감 이후~오늘) 공시가 아니면 호재 점수 미부여
                if any(k in title for k in impact_keywords):
                    clean_d = re.sub(r'^\([^\)]+\)\s*', '', title)
                    clean_d = re.sub(r'^(주|\(주\)|주식회사|비나텍주식회사|삼성바이오로직스\(주\)|삼성이앤에이\(주\))\s*', '', clean_d)
                    full_disc_title = f"[공시] {clean_d}"
                    imp = classify_catalyst_impact(full_disc_title, name=short_name, sector=sector, code=code, is_disclosure=True)
                    disc_info = {
                        'title': full_disc_title,
                        'url': f"https://m.stock.naver.com/domestic/stock/{code}/disclosure",
                        'source': 'DART 전자공시',
                        'body': f"{name} 금융감독원 전자공시시스템(DART) 주요 경영사항 공시",
                        **imp,
                    }
                    break
    except Exception:
        pass

    # 2. 실시간 종목 뉴스 클러스터 전수 분석 (최대 30개 — 호재 가점은 당일 기준, 악재 감시는 최근 3일 감시)
    market_noise = [
        '코스피', '코스닥', '지수', '마감시황', '시황종합', '환율', '외인', '외국인 반도체',
        '투자30', '마켓뷰', '오후시황', '장중 4%', '5500선', '5400선', 'IPO 철회', '코스피5550', '프리마켓서',
    ]

    news_candidates = []
    try:
        url_news = f'https://m.stock.naver.com/api/news/stock/{code}?pageSize=30&page=1'
        req_news = urllib.request.Request(url_news, headers=headers)
        with urllib.request.urlopen(req_news, timeout=3) as resp:
            clusters = json.loads(resp.read().decode('utf-8'))
            for cl in clusters:
                for it in cl.get('items', []):
                    raw_n_dt = str(it.get('datetime') or '')
                    n_dt = re.sub(r'[^0-9]', '', raw_n_dt)[:8]
                    if n_dt and n_dt not in recent_3d_dates:
                        continue  # 3일 지난 오래된 기사 제외
                    is_fresh_today = _is_today_fresh(raw_n_dt)
                    raw_title = it.get('titleFull') or it.get('title', '')
                    title = html.unescape(raw_title).replace('<b>', '').replace('</b>', '').strip()
                    title = re.sub(r'\[종\.\.\.?\]?', '', title).strip()
                    title = re.sub(r'\.\.\.$', '', title).strip()

                    is_about_stock = any(alias in title for alias in aliases) if aliases else True
                    if not is_about_stock:
                        continue  # 타 종목 시황 노이즈(예: 삼전닉스 기사) 원천 배제
                    is_noise = any(n in title for n in market_noise) and not ('[특징주]' in title and is_about_stock)
                    if is_noise:
                        continue

                    body_txt = html.unescape(it.get('body', '')).replace('<b>', '').replace('</b>', '').strip()
                    body_clean = re.sub(r'\s+', ' ', body_txt)[:110]
                    imp = classify_catalyst_impact(title, body=body_clean, name=short_name, sector=sector, code=code, is_disclosure=False)
                    if not is_fresh_today and imp.get('score_delta', 0) > 0:
                        # 어제 장중 이전의 지난 호재 기사는 당일 점수 가산에서 제외 (중립 B급 0점 처리)
                        imp = {'tier': 'B', 'score_delta': 0.0, 'tier_label': '⚪B급 기반영 뉴스(0점)', 'has_hard_catalyst': False}

                    # 후보 정렬 점수: 해당 종목 전용 기사(50) + 등급별 우선순위(S+/S/A 또는 중요 F/C 신호 포착)
                    rank_score = 50 + int(abs(imp['score_delta']) * 2) + (15 if '[특징주]' in title else 0)
                    url = it.get('mobileNewsUrl')
                    if not url and it.get('officeId') and it.get('articleId'):
                        url = f"https://n.news.naver.com/mnews/article/{it['officeId']}/{it['articleId']}"
                    if not url:
                        url = f"https://m.stock.naver.com/domestic/stock/{code}/news"

                    news_candidates.append({
                        'title': title,
                        'url': url,
                        'source': it.get('officeName', '증권뉴스'),
                        'body': body_clean,
                        'score': rank_score,
                        **imp,
                    })
    except Exception as e:
        logger.warning(f"뉴스 수집 예외 ({code}): {e}")

    news_candidates.sort(key=lambda x: x['score'], reverse=True)

    # DART S+/S급 확정 공시가 있고 뉴스에 F급 악재가 없다면 DART 확정 공시 우선 채택
    has_f_news = next((c for c in news_candidates if c.get('tier') == 'F'), None)
    if has_f_news:
        res = {k: v for k, v in has_f_news.items() if k != 'score'}
    elif disc_info and disc_info.get('tier') in ('S+', 'S'):
        res = disc_info
    elif news_candidates:
        best = news_candidates[0]
        res = {k: v for k, v in best.items() if k != 'score'}
    elif disc_info:
        res = disc_info
    else:
        res = {
            'title': f"{short_name} 기관·외인 대량 수급 유입 및 업종 주도 모멘텀",
            'url': f"https://m.stock.naver.com/domestic/stock/{code}/news",
            'source': '실시간 수급',
            'body': '당일 거래대금 폭발 및 지지저항 돌파 주도주',
            'tier': 'B',
            'score_delta': 0.0,
            'tier_label': '⚪B급 수급 모멘텀(0점)',
            'has_hard_catalyst': False,
        }

    _CATALYST_CACHE[cache_key] = res
    return res


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


_ETF_BRAND_PREFIX_RE = re.compile(
    r'^(?:KODEX|TIGER|RISE|KBSTAR|ACE|SOL|PLUS|HANARO|KOSEF|KOACT|'
    r'TIMEFOLIO|TIME|ARIRANG|KIWOOM|WON|WOORI|BNK|HK|1Q|VITA|'
    r'FOCUS|TREX|SMART|TRUSTON|UNICORN|KINDEX|MAESTRO|HEROES|히어로즈|QV|TRUE|N2)\b',
    re.IGNORECASE,
)
_NON_STOCK_DERIV_RE = re.compile(
    r'(?:리츠$|이리츠코크렙|\bETF\b|\bETN\b|\bSPAC\b|\bREIT\b)',
    re.IGNORECASE,
)
_ISSUER_DERIV_RE = re.compile(
    r'(?:삼성|신한|KB|미래에셋|NH|하나|대신|메리츠|키움|한화|유진|IBK|교보)\s+.*(?:ETN|ETF|선물|채권|인버스|레버리지|2X)',
    re.IGNORECASE,
)


def is_common_stock(row):
    """보통주 필터링 (우선주, 스팩, ETF, ETN, 채권, 리츠, 인버스/레버리지, 신주인수권 원천 제외)"""
    stock_end_type = str(row.get('StockEndType') or '').strip().lower()
    if stock_end_type and stock_end_type != 'stock':
        return False
    name = str(row.get('Name', '')).strip()
    code = str(row.get('Code', '')).strip().upper()
    if len(code) != 6 or not code.isalnum():
        return False
    if code[-1] != '0':  # 우선주 제외 (0으로 끝나는 본주만 허용)
        return False
    if _ETF_BRAND_PREFIX_RE.search(name) or _NON_STOCK_DERIV_RE.search(name) or _ISSUER_DERIV_RE.search(name):
        return False
    up_name = name.upper()
    exclude_keywords = [
        '스팩', '선물', '인버스', '레버리지', '채권', '국채', '국고채', '회사채', '통안채',
        '금융채', '물가채', '단기채', '초단기', '머니마켓', 'MMF', 'KOFR', 'CD금리', 'SOFR',
        '원자재', '금현물', '은현물', '원유', '천연가스', '액티브', '커버드콜',
        '맥쿼리인프라', '맵스리얼티', '(합성', '합성H', '(H)', 'TR)',
        'KODEX', 'TIGER', 'RISE', 'KBSTAR', 'HANARO', 'KOSEF', 'KOACT', 'TIMEFOLIO', 'ARIRANG',
    ]
    if any(k in up_name for k in exclude_keywords):
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
    seen_codes = set()
    # 코스피/코스닥 시총 상위 200개 + 당일 상승률/수급 상위 100개 병합 스캔 (시총 200위 밖 3,000~5,500억 알짜 주도주 누락 방지)
    for mkt in ['KOSPI', 'KOSDAQ']:
        pool_urls = [
            f'https://m.stock.naver.com/api/stocks/marketValue/{mkt}?page=1&pageSize=100',
            f'https://m.stock.naver.com/api/stocks/marketValue/{mkt}?page=2&pageSize=100',
            f'https://m.stock.naver.com/api/stocks/up/{mkt}?page=1&pageSize=100',
        ]
        for url in pool_urls:
            try:
                r = requests.get(url, headers=headers, timeout=4)
                if r.status_code == 200:
                    stocks = r.json().get('stocks', [])
                    for s in stocks:
                        stock_end_type = str(s.get('stockEndType') or '').strip().lower()
                        if stock_end_type and stock_end_type != 'stock':
                            continue
                        code = str(s.get('itemCode') or '').strip()
                        name = s.get('stockName')
                        close_p = s.get('closePriceRaw')
                        chg_pct = s.get('fluctuationsRatio')
                        amt_raw = s.get('accumulatedTradingValueRaw', 0)
                        mc_raw = s.get('marketValueRaw', 0)
                        if code and close_p and code not in seen_codes:
                            seen_codes.add(code)
                            items.append({
                                'Code': code,
                                'Name': str(name),
                                'Market': mkt,
                                'StockEndType': stock_end_type or 'stock',
                                'Close': float(close_p),
                                'Open': float(close_p),
                                'High': float(close_p),
                                'Low': float(close_p),
                                'ChagesRatio': float(chg_pct) if chg_pct else 0.0,
                                'Amount': float(amt_raw) if amt_raw else 0.0,
                                'Marcap': float(mc_raw) if mc_raw else 0.0
                            })
            except Exception as e:
                logger.debug(f"네이버 실시간 시세 {mkt} 수집 예외: {e}")

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
    스윙 목표가 & 손절가 산출 (+2.5% 조기 본절 잠금 / 1차 +5.0% / 2차 +9.0% / 손절 -3.0%)
    - 손익비: 1차 1.67 : 1, 2차 3.00 : 1 (평균 2.33 : 1) + +2.5% 터치 시 손절선 본절(+0.3%) 조기 상향
    - 20일선 눌림목 반등 타겟: +2.5% 본절 잠금 → 1차 +5% 50% 분할 익절 → 2차 +9% 전량 익절
    """
    return {
        'mode': 'TREND',
        'mode_label': '🚀 2~5일 스윙 (추세 파동)',
        'mode_desc': '20일선 눌림목 반등 타겟: +2.5% 터치 시 조기 본절(+0.3%) 잠금 → 1차 +5% 50% 분할 익절 → 2차 +9% 전량 익절',
        'target_1': int(round(close_p * 1.05)),
        'target_1_pct': '+5.0%',
        'target_2': int(round(close_p * 1.09)),
        'target_2_pct': '+9.0%',
        'target_3': None,
        'target_3_pct': None,
        'stop_loss': int(round(close_p * 0.97)),
        'stop_loss_pct': '-3.0%',
        'holding_period': '2~5영업일 분할 매도 (+2.5% 조기 본절 잠금 → 1차 +5.0% 50% 익절 → 2차 +9.0% 잔량 전량 익절)',
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
        res = requests.get(url, timeout=2.5)
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

        # 5일선·20일선·60일선 이동평균 및 이격도 · 5일 누적 상승률
        ma5 = sum(r['close'] for r in rows[-5:]) / 5.0
        ma20 = sum(r['close'] for r in rows[-20:]) / 20.0
        ma20_prev = sum(r['close'] for r in rows[-24:-4]) / 20.0 if len(rows) >= 24 else ma20
        ma60 = sum(r['close'] for r in rows[-60:]) / len(rows[-60:]) if len(rows) >= 60 else None
        disp5_pct = round(((today_close - ma5) / ma5) * 100.0, 2) if ma5 > 0 else 0.0
        disp20_pct = round(((today_close - ma20) / ma20) * 100.0, 2) if ma20 > 0 else 0.0
        disp60_pct = round(((today_close - ma60) / ma60) * 100.0, 2) if (ma60 and ma60 > 0) else 0.0
        base_5d_close = rows[-6]['close'] if len(rows) >= 6 else rows[0]['close']
        chg_5d_pct = round(((today_close - base_5d_close) / base_5d_close) * 100.0, 2) if base_5d_close > 0 else 0.0

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
            'ma5': ma5,
            'ma20': ma20,
            'ma20_prev': ma20_prev,
            'disp5_pct': disp5_pct,
            'disp20_pct': disp20_pct,
            'disp60_pct': disp60_pct,
            'chg_5d_pct': chg_5d_pct,
            'tags': tags
        }
    except Exception as e:
        logger.debug(f"{code} 지지저항 분석 실패: {e}")
        return None


def _parse_signed_int(val) -> int:
    try:
        return int(str(val or '0').replace(',', '').replace('+', '').strip())
    except Exception:
        return 0


def fetch_stock_major_flow(code: str, toxic_lookback_days: int = 14) -> dict:
    """
    종목별 최근 3영업일 외국인·기관 순매수 수급 및 희석/리스크 악재 공시 여부를 조회합니다.
    GitHub Actions 등 키움 API 키가 없는 환경에서도 동작하도록 네이버 모바일 API를 사용합니다.
    """
    import requests
    headers = {'User-Agent': 'Mozilla/5.0'}
    out = {
        'foreign_3d': 0,
        'organ_3d': 0,
        'foreign_latest': 0,
        'organ_latest': 0,
        'is_dual_buy': False,
        'is_organ_accum': False,
        'is_major_dump': False,
        'toxic_disclosure': None,
    }
    try:
        r = requests.get(f'https://m.stock.naver.com/api/stock/{code}/integration', headers=headers, timeout=2.5)
        if r.status_code == 200:
            infos = (r.json() or {}).get('dealTrendInfos', [])[:3]
            if infos:
                out['foreign_latest'] = _parse_signed_int(infos[0].get('foreignerPureBuyQuant'))
                out['organ_latest'] = _parse_signed_int(infos[0].get('organPureBuyQuant'))
                out['foreign_3d'] = sum(_parse_signed_int(x.get('foreignerPureBuyQuant')) for x in infos)
                out['organ_3d'] = sum(_parse_signed_int(x.get('organPureBuyQuant')) for x in infos)
                out['is_dual_buy'] = (
                    (out['foreign_3d'] > 0 and out['organ_3d'] > 0)
                    or (out['foreign_latest'] > 0 and out['organ_latest'] > 0)
                )
                out['is_organ_accum'] = (not out['is_dual_buy']) and (out['organ_3d'] > 0 and out['organ_latest'] > 0)
                out['is_major_dump'] = (out['foreign_3d'] < 0 and out['organ_3d'] < 0 and out['organ_latest'] < 0)
    except Exception as e:
        logger.debug(f"{code} 외인/기관 수급 조회 예외: {e}")

    try:
        r_disc = requests.get(f'https://m.stock.naver.com/api/stock/{code}/disclosure?pageSize=8&page=1', headers=headers, timeout=2.0)
        if r_disc.status_code == 200:
            discs = r_disc.json() or []
            toxic_keywords = [
                '유상증자', '전환사채', '신주인수권부사채', '교환사채', '전환청구권', '신주인수권행사',
                '추가상장', '감자결정', '무상감자', '자기주식처분', '시간외대량매매', '블록딜',
                '불성실공시', '거래정지', '관리종목', '투자경고', '투자위험', '단기과열',
                '공매도 과열', '감사의견', '횡령', '배임', '부도', '회생', '계약해지', '공급계약해지',
            ]
            recent_toxic_dates = {
                (datetime.now(KST) - timedelta(days=offset)).strftime('%Y%m%d')
                for offset in range(max(1, int(toxic_lookback_days)) + 1)
            }
            for d in discs:
                title = str(d.get('title', ''))
                dt_str = re.sub(r'[^0-9]', '', str(d.get('datetime') or d.get('date') or d.get('regDt') or ''))[:8]
                is_recent = (not dt_str) or (dt_str in recent_toxic_dates)
                is_bad_amend = ('기재정정' in title and any(ak in title for ak in ('합병', '유상증자', '전환사채', '단일판매', '공급계약', '타법인')))
                if is_recent and (any(tk in title for tk in toxic_keywords) or is_bad_amend):
                    out['toxic_disclosure'] = title[:60]
                    break
    except Exception as e:
        logger.debug(f"{code} 악재 공시 점검 예외: {e}")

    return out


def _resolve_ai_risk_score(market_context=None) -> int:
    """market_context에 ai_risk_score가 있으면 사용하고, 없으면 실시간 리스크를 보수적으로 산출합니다."""
    if market_context and market_context.get('ai_risk_score') is not None:
        return int(market_context['ai_risk_score'])
    try:
        from src.risk_score import compute_risk_score
        from src.market_score import fetch_kr_market, fetch_nasdaq_futures, fetch_cnn_fear_greed, fetch_vix
        _, fut_r = fetch_nasdaq_futures()
        _, kp_r, _, _, kp_fn, kp_in = fetch_kr_market('KOSPI')
        _, kd_r, _, _, kd_fn, kd_in = fetch_kr_market('KOSDAQ')
        cnn_s, _ = fetch_cnn_fear_greed()
        vix_v, _ = fetch_vix()
        return int(compute_risk_score({
            'fut_ratio': fut_r if fut_r is not None else 0.0,
            'kp_ratio': kp_r if kp_r is not None else 0.0,
            'kd_ratio': kd_r if kd_r is not None else 0.0,
            'kp_for_num': kp_fn or 0,
            'kp_inst_num': kp_in or 0,
            'kd_for_num': kd_fn or 0,
            'kd_inst_num': kd_in or 0,
            'cnn_score': cnn_s if cnn_s is not None else 50.0,
            'vix': float(str(vix_v).replace(',', '')) if vix_v else 20.0,
        }))
    except Exception as e:
        logger.warning(f"AI 리스크 점수 산출 실패 → 보수적 기본값 50점 적용 (원인 확인 필요): {e}")
        return 50


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

    # [신규] BiniStock 주요일정 & D-Day 호재 인텔리전스 (시총 대비 소각 비중 % 등)
    event_boost_map = {}
    event_intel = {}
    try:
        try:
            from src.event_manager import build_and_save_event_intelligence
        except ImportError:
            from event_manager import build_and_save_event_intelligence
        event_intel = build_and_save_event_intelligence()
        event_boost_map = event_intel.get("stock_boost_map", {})
    except Exception as e:
        logger.debug(f"이벤트 인텔리전스 연동 예외: {e}")

    # =========================================================================
    # Track 1: 🎯 오늘 15:10 종가베팅 (오버나잇)
    # =========================================================================
    # [시장 등락비율 Breadth 산출: 상승종목 / (상승+하락종목) 비율 %]
    breadth_pct = 50.0
    try:
        adv_cnt = int((common['ChagesRatio'] > 0).sum())
        dec_cnt = int((common['ChagesRatio'] < 0).sum())
        if (adv_cnt + dec_cnt) > 0:
            breadth_pct = round((adv_cnt / (adv_cnt + dec_cnt)) * 100.0, 1)
    except Exception:
        breadth_pct = 50.0

    # [아이디어 5] 오늘의 최강 주도 섹터 TOP 3 및 섹터별 1등 대장주 집계
    hot_sectors = []
    hot_sector_names = []
    hot_leader_codes = set()
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
            leader_rank = (schg * 0.6) + min(samt / 200.0, 15.0)
            if ssec not in sec_agg:
                sec_agg[ssec] = {
                    'sector': ssec, 'count': 0, 'total_amount_eok': 0,
                    'chg_sum': 0.0, 'leader_name': sname, 'leader_code': scode,
                    'leader_chg': schg, '_leader_rank': leader_rank,
                }
            sec_agg[ssec]['count'] += 1
            sec_agg[ssec]['total_amount_eok'] += int(samt)
            sec_agg[ssec]['chg_sum'] += schg
            if samt >= 300 and leader_rank > sec_agg[ssec]['_leader_rank']:
                sec_agg[ssec]['leader_name'] = sname
                sec_agg[ssec]['leader_code'] = scode
                sec_agg[ssec]['leader_chg'] = round(schg, 2)
                sec_agg[ssec]['_leader_rank'] = leader_rank
        for k, v in sec_agg.items():
            v['avg_chg'] = round(v['chg_sum'] / max(v['count'], 1), 2)
            v.pop('_leader_rank', None)
            hot_sectors.append(v)
        hot_sectors.sort(key=lambda x: (x['count'], x['total_amount_eok']), reverse=True)
        hot_sectors = hot_sectors[:3]
        hot_sector_names = [h['sector'] for h in hot_sectors[:2]]
        hot_leader_codes = {h['leader_code'] for h in hot_sectors[:2] if h.get('leader_code')}
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

    risk_val = _resolve_ai_risk_score(market_context)
    is_low_risk_market = (risk_val <= 45)
    max_chg_cap = 15.0 if is_low_risk_market else 10.0

    closing_picks = []
    # [안정성+탄력 병행 종가베팅 주도주 선별]
    # 1) 시가총액: 3,000억 이상 ~ 30조 원 이하 (초대형 지수주·잡주 배제)
    # 2) 당일 거래대금: 최소 300억 이상 (10% 초과 S급 기준봉 예외 시 500억+ 필수)
    # 3) 당일 주가 상승률: 기본 +3.5% ~ +10.0%, 단 AI 리스크 45점 이하일 때만 +15.0%까지 S급 첫출발 기준봉 조건부 허용
    closing_pool = common[
        (common['Marcap'] >= 3000 * 1e8) &      # 시총 3,000억 이상
        (common['Marcap'] <= 300000 * 1e8) &    # 시총 30조 원 이하 (10~25조 S급 대형 주도주 포용, 30조 초과 초거대 지수주 배제)
        (common['Amount'] >= 300 * 1e8) &       # 당일 거래대금 최소 300억 이상 (주도주 수급 보장)
        (common['ChagesRatio'] >= 3.5) &        # 최소 +3.5% 이상
        (common['ChagesRatio'] <= max_chg_cap)  # +10% (AI 리스크 <= 45일 때 최대 +15% 조건부 허용)
    ].copy()

    # 거래대금 상위 30개 종목 압축 (AI 리스크가 높더라도 종목·점수는 숨기지 않고 100% 투명하게 산출!)
    closing_pool = closing_pool.sort_values(by='Amount', ascending=False).head(30)
    if risk_val > 60 or str((regime or {}).get('status', 'neutral')).lower() == 'panic':
        logger.info(f"[종가베팅 시황 주의] AI 리스크 {risk_val}점 (>60점) ➔ 종목·점수는 투명하게 표시하되 실전 자동매수는 차단합니다.")
    all_closing_evaluated = []

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

        # +10.0% ~ +15.0% 구간은 5중 안전 게이트 충족 S급 기준봉에만 조건부 허용 (대금 500억↑ · 꼬리 25%↓ · 몸통 55%↑)
        if change_pct > 10.0:
            if not is_low_risk_market:
                logger.info(f"[종가베팅 과열 차단] {name}({code}): +{change_pct:.1f}% (리스크 {risk_val}점 > 45점 보수 상한 +10%)")
                continue
            if amount_eok < 500 or head_ratio > 0.25 or body_ratio < 0.55:
                logger.info(
                    f"[종가베팅 S급 기준봉 미달] {name}({code}): +{change_pct:.1f}% "
                    f"(대금 {int(amount_eok)}억/500억, 윗꼬리 {int(head_ratio*100)}%/25%, 몸통 {int(body_ratio*100)}%/55%)"
                )
                continue

        # 윗꼬리 38% 이하 & 양봉 몸통 35% 이상 엄격 필터링 (미달 시에도 화면 점수 공개용 후보 풀에는 감점 후 보존)
        filter_fail_reasons = []
        if head_ratio > 0.38 or body_ratio < 0.35:
            filter_fail_reasons.append(f"⚠️캔들기준미달(윗꼬리 {int(head_ratio*100)}%/몸통 {int(body_ratio*100)}%)")

        sr = analyze_support_resistance(code, name)
        if sr and not sr.get('is_valid', True):
            logger.info(f"[종가베팅 필터 탈락] {name}({code}): {sr.get('reject_reason')}")
            filter_fail_reasons.append(f"⚠️{sr.get('reject_reason')}")

        sr_score = sr.get('sr_score', 0.0) if sr else 0.0
        sr_status = sr.get('status', '거래대금 수급 우수') if sr else '거래대금 수급 우수'
        support_price = sr.get('support_price', int(close_p * 0.98)) if sr else int(close_p * 0.98)
        next_res = sr.get('next_res', f"{int(close_p * 1.05):,}원") if sr else f"{int(close_p * 1.05):,}원"
        room_pct = sr.get('room_pct', 5.0) if sr else 5.0
        sr_tags = sr.get('tags', []) if sr else []
        rvol = sr.get('rvol', 1.5) if sr else 1.5
        disp5_pct = sr.get('disp5_pct', 0.0) if sr else None
        disp20_pct = sr.get('disp20_pct', 0.0) if sr else 0.0
        disp60_pct = sr.get('disp60_pct', 0.0) if sr else 0.0
        chg_5d_pct = sr.get('chg_5d_pct', 0.0) if sr else 0.0
        turnover_pct = round((amount_eok / (marcap / 1e8)) * 100, 2) if marcap > 0 else 0.0
        stock_sec = get_stock_sector(code)

        # 20일선(+28%) / 60일선(+50%) / 5거래일 누적(+35%) 초과 과열 상투 구간 방어
        overheat_msgs = []
        if disp20_pct > 28.0:
            overheat_msgs.append(f"20일선+{disp20_pct:.1f}%")
        if disp60_pct > 50.0:
            overheat_msgs.append(f"60일선+{disp60_pct:.1f}%")
        if chg_5d_pct > 35.0:
            overheat_msgs.append(f"5일누적+{chg_5d_pct:.1f}%")
        if overheat_msgs:
            logger.info(f"[종가베팅 이격과열 상투 차단] {name}({code}): {', '.join(overheat_msgs)}")
            filter_fail_reasons.append(f"⚠️이격과열상투({', '.join(overheat_msgs)})")

        # +10% ~ +15% 구간: 일봉 조회 실패 시 별도 표기, 정상 조회 시 5일선 이격 +13.0% 초과 극단 괴리 또는 (+10.0% 초과 & 5거래일 누적 +18.0% 초과 연속급등 상투)만 차단
        if change_pct > 10.0:
            if disp5_pct is None:
                logger.info(f"[종가베팅 일봉조회 실패 차단] {name}({code}): +{change_pct:.1f}% 일봉 지지·이격 확인 불가")
                filter_fail_reasons.append("⚠️일봉조회실패")
            elif disp5_pct > 13.0 or (disp5_pct > 10.0 and chg_5d_pct > 18.0):
                logger.info(
                    f"[종가베팅 연속급등 상투 차단] {name}({code}): +{change_pct:.1f}% "
                    f"5일선 이격 +{disp5_pct:.1f}% / 5일누적 +{chg_5d_pct:.1f}%"
                )
                filter_fail_reasons.append(f"⚠️5일선이격과열(+{disp5_pct:.1f}%/5일+{chg_5d_pct:.1f}%)")

        min_req_turnover = 0.4 if marcap >= 50000 * 1e8 else 1.0
        if turnover_pct < min_req_turnover and amount_eok < 700:
            logger.info(
                f"[종가베팅 필터 탈락] {name}({code}): 시총({marcap_str}) 대비 거래대금({int(amount_eok):,}억) "
                f"회전율 부족 ({turnover_pct:.2f}% < 기준 {min_req_turnover:.1f}%)"
            )
            filter_fail_reasons.append(f"⚠️회전율부족({turnover_pct:.2f}%)")

        micro = analyze_intraday_microstructure(code, close_p)
        if micro and micro.get('is_morning_dump'):
            logger.info(f"[종가베팅 필터 탈락] {name}({code}): 오전 고점({micro.get('peak_time')}) 후 오후 VWAP 하회 설거지 패턴")
            filter_fail_reasons.append(f"⚠️오후VWAP하회(고점 {micro.get('peak_time')})")
        if change_pct > 10.0:
            vwap_diff_now = micro.get('vwap_diff_pct', -1.0) if micro else -1.0
            if vwap_diff_now <= 0.0:
                logger.info(f"[종가베팅 VWAP 미달 차단] {name}({code}): +{change_pct:.1f}% 당일 VWAP 하회({vwap_diff_now:+.2f}%)")
                filter_fail_reasons.append("⚠️당일VWAP하회")

        major_flow = fetch_stock_major_flow(code, toxic_lookback_days=7)
        if major_flow.get('toxic_disclosure'):
            logger.warning(f"[종가베팅 악재 공시 차단] {name}({code}): {major_flow['toxic_disclosure']}")
            filter_fail_reasons.append(f"🚨악재공시({major_flow['toxic_disclosure'][:18]})")

        if True:

            # [정석 B: 기본 40점 고정 + 핵심 실력 55점 + 알파 보너스 20점 = 최대 115점 → 99점 상한]
            # 핵심 실력(55점): 거래대금(13) + 대형주 보정 회전율(5) + 돌파(14) + 캔들(8) + RVOL(4) + VWAP(4) + 외인·기관(7)
            # 알파 보너스(20점): 동시호가(2) + 주도섹터(4) + 1등대장/고승률(4) + 뉴스·공시(S+ 10 / S 8 / A 5 / B 0 / C -8 / F -20)
            abs_vol_score = min((amount_eok / 500.0) * 13.0, 13.0)               # 거래대금 500억 이상 13점 만점
            turn_req_pct = 0.5 if marcap >= 50000 * 1e8 else 3.0                 # 시총 5조↑ 대형주는 회전율 0.5% 만점, 일반주는 3.0% 만점
            turnover_score = min((turnover_pct / turn_req_pct) * 5.0, 5.0)       # 최대 5점
            volume_score = abs_vol_score + turnover_score                        # 수급 규모 최대 18점
            sr_weighted = 14.0 if sr_score >= 25.0 else (12.0 if sr_score >= 15.0 else (9.0 if sr_score > 0 else 0.0))
            candle_score = max(0.0, (1.0 - head_ratio) * 8.0)                    # 최대 8점 (+ sr_weighted 14점 = 차트 22점)
            score = 40.0 + volume_score + sr_weighted + candle_score
            
            # 기존 AI 포착 근거 100% 보존 + 회전율 및 지지·저항 차트 근거 추가
            reasons = [
                f"거래대금 {int(amount_eok):,}억 폭발(시총회전율 {turnover_pct:.1f}%)",
                f"고가 마감 양봉(윗꼬리 {int(head_ratio*100)}%)"
            ]
            if sr_status:
                reasons.append(f"차트: {sr_status}")
            if rvol > 1.0:
                score += min(((rvol - 1.0) / 1.2) * 4.0, 4.0)                    # RVOL 최대 4점 (2.2배 만점)
                if rvol >= 2.0:
                    reasons.append(f"상대거래량 RVOL {rvol:.1f}배(회전율 {turnover_pct:.1f}%)")
            if micro:
                vwap_diff = micro.get('vwap_diff_pct', 0.0)
                peak_t = micro.get('peak_time', '')
                auc_diff = micro.get('closing_auction_diff', 0.0)
                if vwap_diff >= 0:
                    score += 4.0
                    reasons.append(f"당일 VWAP 상회(+{vwap_diff:.1f}% · 고점 {peak_t})")
                if auc_diff >= 0.3:
                    score += 2.0
                    reasons.append(f"막판 동시호가 수급 유입(+{auc_diff:.2f}%)")
            sec_bonus = 0.0
            if stock_sec in hot_sector_names:
                sec_bonus += 4.0
                reasons.append(f"🔥당일 주도섹터({stock_sec}) 동조화")
            leader_or_win = False
            if code in hot_leader_codes:
                leader_or_win = True
                reasons.append(f"👑주도섹터({stock_sec}) 1등 대장주")
            if stock_sec in winning_sectors:
                leader_or_win = True
                reasons.append("🧠30일 고승률 섹터 자가보정")
            if leader_or_win:
                sec_bonus += 4.0
            score += min(sec_bonus, 8.0)                                         # 섹터·주도력 보너스 최대 8점

            tags = ['거래대금폭발', '단단한양봉', '익일시초가노림'] + sr_tags
            if code in hot_leader_codes:
                tags.append("섹터1등대장")
            if change_pct > 10.0 and disp5_pct is not None:
                reasons.append(f"🔥S급 첫출발 기준봉(5일선이격 +{disp5_pct:.1f}%)")
                tags.append("S급기준봉")

            if major_flow.get('is_dual_buy'):
                score += 7.0
                reasons.append("🏦외인·기관 쌍끌이 수급 유입(+7점)")
                tags.append("쌍끌이수급")
            elif major_flow.get('is_organ_accum'):
                score += 5.5
                reasons.append("🏦기관 연속 순매수 매집(+5.5점)")
                tags.append("기관매집")
            elif major_flow.get('is_major_dump'):
                score -= 5.0
                reasons.append("⚠️최근 3일 외인·기관 동시 순매도(-5점)")
            else:
                score += 2.0                                                     # 수급 중립 기본 2점 (최대 7점 체계)

            # [5단계 뉴스·공시 정밀 등급(S+ / S / A / B / C / F) 알파 보너스 최대 +10점 / 감점 최대 -20점]
            cat_info = fetch_stock_catalyst(code, name, stock_sec)
            cat_tier = cat_info.get('tier', 'B')
            if code in catalyst_codes and cat_tier not in ('S+', 'S', 'C', 'F'):
                cat_tier = 'S'
                cat_info['tier_label'] = '🟢S급 DART 호재 공시(+8점)'
            _cat_weight_map = {'S+': 10.0, 'S': 8.0, 'A': 5.0, 'B': 0.0, 'C': -8.0, 'F': -20.0}
            cat_score = _cat_weight_map.get(cat_tier, 0.0)
            ev_info = event_boost_map.get(name) or event_boost_map.get(code)
            if ev_info and ev_info.get('boost_score', 0) > 0 and cat_tier not in ('C', 'F'):
                cat_score = min(10.0, cat_score + 2.0)
                reasons.append(f"🎯{ev_info.get('tag')} (호재모멘텀)")
                tags.append("D-Day호재모멘텀")
            score += cat_score
            if cat_tier != 'B':
                reasons.append(cat_info.get('tier_label', f"뉴스·공시({cat_tier}등급 {cat_score:+.0f}점)"))
                if cat_tier in ('S+', 'S'):
                    tags.append("실적/공시호재")
                elif cat_score < 0:
                    tags.append("⚠️재료소멸주의")

            # 제약/바이오 윗꼬리 과다(25% 초과) + 수급 부재 시 재료소멸 추가 방어
            if stock_sec == '제약/바이오' and head_ratio > 0.25 and not major_flow.get('is_dual_buy'):
                score -= 6.0
                reasons.append(f"⚠️바이오 윗꼬리({int(head_ratio*100)}%) 재료소멸 주의(-6점)")

            if filter_fail_reasons:
                score -= 10.0 * len(filter_fail_reasons)
                reasons.extend(filter_fail_reasons)
                score = min(score, 84.0)
            if cat_tier == 'F' or major_flow.get('toxic_disclosure'):
                score = min(score, 74.0)
            score = max(0.0, score)
            final_cl_score = int(round(min(score, 99.0)))
            is_sub_cl = (final_cl_score < 90) or bool(filter_fail_reasons)
            cand_item = {
                'code': code,
                'name': name,
                'market': market,
                'sector': stock_sec,
                'price': int(close_p),
                'change_pct': round(change_pct, 2),
                'amount_eok': int(amount_eok),
                'target_1': int(close_p * 1.02),
                'target_1_pct': '+2.0%',
                'target_2': int(close_p * 1.05),
                'target_2_pct': '+5.0%',
                'stop_loss': int(close_p * 0.98),
                'stop_loss_pct': '-2.0%',
                'holding_period': '당일 15:10~15:30 매수 → 익일 09:00~09:20 전량 분할 매도',
                'score': final_cl_score,
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
                'is_breakout': sr.get('is_20_breakout', False) or sr.get('is_60_breakout', False) if sr else False,
                'is_sub_threshold': is_sub_cl,
            }
            all_closing_evaluated.append(cand_item)
            if is_sub_cl:
                logger.info(f"[종가베팅 90점 미달(관망 후보 보존)] {name}({code}): AI 점수 {score:.1f}점 < 기준 90점 (재료등급: {cat_tier})")
                continue

            closing_picks.append(cand_item)

    if not closing_picks and all_closing_evaluated:
        # 90점 이상 종목이 0개인 날에도 상위 2개 차순위 후보의 점수를 숨기지 않고 화면에 투명하게 공개 (단, 자동매수는 차단)
        all_closing_evaluated.sort(key=lambda x: x['score'], reverse=True)
        for sub_p in all_closing_evaluated[:2]:
            sub_p['holding_period'] = f"⏸️ AI {sub_p['score']}점 (<90점 기준 미달) — 화면 점수 공개용 · 자동매수 관망"
            closing_picks.append(sub_p)

    closing_picks.sort(key=lambda x: x['score'], reverse=True)
    # [동일 섹터 쏠림 분산] 1·2등이 같은 섹터에 몰릴 경우 90점+ 타 섹터 최고점 후보를 2번 슬롯에 우선 배치
    if len(closing_picks) >= 3:
        top_sec = closing_picks[0].get('sector', '')
        second_sec = closing_picks[1].get('sector', '')
        generic_secs = ('', '주도주', '기타')
        if top_sec not in generic_secs and top_sec == second_sec:
            for alt_idx in range(2, len(closing_picks)):
                alt_sec = closing_picks[alt_idx].get('sector', '')
                if alt_sec not in generic_secs and alt_sec != top_sec:
                    alt_pick = closing_picks.pop(alt_idx)
                    alt_pick['reason'] = f"{alt_pick.get('reason', '')} · 섹터 분산 우선 배치({top_sec} 중복 회피)"
                    closing_picks.insert(1, alt_pick)
                    logger.info(
                        f"[종가베팅 섹터 분산] {closing_picks[0]['name']}({top_sec}) 중복 회피 ➔ "
                        f"2번 슬롯 {alt_pick['name']}({alt_sec}, {alt_pick['score']}점) 우선 배치"
                    )
                    break
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
    # 1) 시총 3,000억 ~ 30조 원 주도 유망주
    # 2) 당일 거래대금 100억 이상 (소외주/잡주 원천 차단)
    # 3) 당일 양봉 필수 (ChagesRatio >= 0.0 & Close >= Open, 음봉 절대 매수 금지)
    # 4) 20일선 위 5% 이내 눌림목 지지 & 5일선-20일선 정배열
    # 5) AI 종합 점수 90점 이상 엄격 컷오프 (미달 시 추천 없음: 100% 현금 보존)
    closing_picked_codes = {cp['code'] for cp in closing_picks}
    swing_pool = common[
        (common['Marcap'] >= 3000 * 1e8) &     # 시총 3,000억 이상
        (common['Marcap'] <= 300000 * 1e8) &   # 시총 30조 원 이하 (우량 대형 추세주 포용)
        (common['Amount'] >= 100 * 1e8) &      # 당일 거래대금 100억 이상 (주도력 확보)
        (common['ChagesRatio'] >= 0.0) &       # 음봉 배제 (0% 이상 보합/상승)
        (common['ChagesRatio'] <= 6.5) &       # 과열되지 않은 초입 양봉
        (common['Close'] >= common['Open'])    # 당일 시가 대비 양봉 확인
    ].copy()

    # 손절 직후 재추천 방지: 최근 10일 내 -3% 손절로 끝난 종목은 스윙 후보에서 제외 (쿨다운)
    try:
        try:
            from src.swing_track_record import get_recent_stopped_codes
        except ImportError:
            from swing_track_record import get_recent_stopped_codes
        _stopped = get_recent_stopped_codes()
        if _stopped:
            _before = len(swing_pool)
            swing_pool = swing_pool[~swing_pool['Code'].astype(str).isin(_stopped)].copy()
            if len(swing_pool) < _before:
                logger.info(f"[스윙 손절 쿨다운] 최근 손절 종목 {_before - len(swing_pool)}개 후보 제외: {sorted(_stopped)}")
    except Exception as _cd_err:
        logger.debug(f"스윙 쿨다운 적용 예외: {_cd_err}")

    # 거래대금 상위 45개 정예 후보로 압축 후 ThreadPoolExecutor(6스레드) 병렬 고속 분석 (네이버 fchart + FDR 폴백)
    swing_pool = swing_pool.sort_values(by='Amount', ascending=False).head(45)
    start_date_swing = (datetime.now() - timedelta(days=90)).strftime('%Y-%m-%d')

    def _evaluate_swing_candidate(row_dict: dict):
        code = str(row_dict['Code'])
        if code in closing_picked_codes:
            return None
        name = str(row_dict['Name'])
        market = str(row_dict['Market'])
        close_p = float(row_dict['Close'])
        high_p = float(row_dict['High'])
        low_p = float(row_dict['Low'])
        if high_p > low_p and ((high_p - close_p) / (high_p - low_p)) > 0.42:
            return None
        amount_eok = float(row_dict['Amount']) / 1e8
        change_pct = float(row_dict['ChagesRatio'])
        marcap = float(row_dict['Marcap']) if 'Marcap' in row_dict and pd.notnull(row_dict['Marcap']) else 0
        marcap_str = format_marcap(marcap)

        try:
            # 1) 네이버 일봉 fchart 우선 조회 + 머리 위 2.5% 저항선 충돌·역배열 일괄 차단
            sr = analyze_support_resistance(code, name)
            if sr is not None and not sr.get('is_valid', True):
                logger.info(f"[스윙 필터 탈락] {name}({code}): {sr.get('reject_reason')}")
                return None

            if sr is not None and sr.get('ma20') and sr.get('ma20_prev'):
                ma5 = float(sr['ma5'])
                ma20 = float(sr['ma20'])
                ma20_prev = float(sr['ma20_prev'])
            else:
                df = fdr.DataReader(code, start=start_date_swing)
                if len(df) < 25:
                    return None
                closes = df['Close'].values[-25:]
                ma5 = float(pd.Series(closes).rolling(5).mean().values[-1])
                ma20 = float(pd.Series(closes).rolling(20).mean().values[-1])
                ma20_prev = float(pd.Series(closes).rolling(20).mean().values[-5])

            # 20일선 우상향 & 5일선-20일선 정배열
            is_uptrend = ma20 >= ma20_prev
            is_golden = ma5 >= ma20 * 0.995
            dist_ma20 = (close_p - ma20) / close_p * 100
            is_near_ma20 = (close_p >= ma20) and (dist_ma20 <= 5.0)
            if not (is_uptrend and is_golden and is_near_ma20):
                return None

            # 2) 장중 분봉 미시구조 분석: 오전 고점 후 오후 VWAP 하회 설거지 패턴 차단
            micro = analyze_intraday_microstructure(code, close_p)
            if micro and micro.get('is_morning_dump'):
                logger.info(f"[스윙 필터 탈락] {name}({code}): 오전 고점({micro.get('peak_time')}) 후 VWAP 하회 설거지 패턴")
                return None

            # 3) 최근 3일 외인·기관 수급 및 14일 희석 악재 공시 차단
            major_flow = fetch_stock_major_flow(code, toxic_lookback_days=14)
            if major_flow.get('toxic_disclosure'):
                logger.warning(f"[스윙 악재 공시 차단] {name}({code}): {major_flow['toxic_disclosure']}")
                return None

            # AI 리스크가 60점을 초과하더라도 스윙 후보의 점수는 숨기지 않고 산출하여 화면에 표시 (실제 매수 차단은 매매봇에서 수행)
            regime_status = str((regime or {}).get('status', 'neutral')).lower()
            if risk_val > 60 or regime_status == 'panic':
                logger.info(f"[스윙 시황 주의] {name}({code}): AI 리스크 {risk_val}점 (>60점) ➔ 종목·점수는 표시하되 자동매수는 보류")

            score = 68.0 + min(amount_eok / 70, 15.0) + (5.0 - dist_ma20) * 3.5
            reasons = [f"20일선({int(ma20):,}원) 눌림목 지지", f"이격도 {dist_ma20:.1f}% 안정 구간"]
            if dist_ma20 <= 2.0:
                score += 3.0
                reasons.append("20일선 초밀착 지지(+3점)")
            tags = ['20일선눌림목', '추세우상향', '안정적손익비']

            if sr:
                if sr.get('is_60_breakout'):
                    score += 15.0
                    reasons.append(sr.get('status', '60일 신고가 돌파'))
                    tags.extend(sr.get('tags', []))
                elif sr.get('is_20_breakout'):
                    score += 10.0
                    reasons.append(sr.get('status', '20일 박스권 상단 돌파'))
                    tags.extend(sr.get('tags', []))

            if micro and micro.get('vwap_diff_pct', -1.0) >= 0:
                score += 3.0
                reasons.append(f"당일 VWAP 상회(+{micro['vwap_diff_pct']:.1f}%)")

            if major_flow.get('is_dual_buy'):
                score += 7.0
                reasons.append("🏦외인·기관 쌍끌이 매수(+7점)")
                tags.append("쌍끌이수급")
            elif major_flow.get('is_organ_accum'):
                score += 4.0
                reasons.append("🏦기관 연속 순매수(+4점)")
            elif major_flow.get('is_major_dump'):
                score -= 5.0
                reasons.append("⚠️외인·기관 동시 순매도(-5점)")

            stock_sec_sw = get_stock_sector(code)
            cat_info_sw = fetch_stock_catalyst(code, name, stock_sec_sw)
            cat_tier_sw = cat_info_sw.get('tier', 'B')
            cat_delta_sw = float(cat_info_sw.get('score_delta', 0.0))
            if code in catalyst_codes and cat_tier_sw not in ('C', 'F') and cat_delta_sw < 12.0:
                cat_delta_sw = 12.0
                cat_tier_sw = 'S'
                cat_info_sw['tier_label'] = '🟢S급 실적/호재 공시(+12점)'
            if cat_delta_sw != 0.0:
                score += cat_delta_sw
                reasons.append(cat_info_sw.get('tier_label', f"뉴스·공시({cat_delta_sw:+.0f}점)"))
                if cat_delta_sw >= 10.0:
                    tags.append("실적모멘텀")

            ev_info = event_boost_map.get(name) or event_boost_map.get(code)
            if ev_info:
                b_score = ev_info.get('boost_score', 0)
                if b_score > 0:
                    score += b_score
                    reasons.append(f"🎯{ev_info.get('tag')} (+{b_score}점)")
                    tags.append("D-Day호재모멘텀")

            if cat_tier_sw == 'F':
                score = min(score, 74.0)
            score = min(99.0, max(0.0, score))
            final_sw_score = int(round(min(score, 99.0)))
            if final_sw_score < 85:
                logger.info(f"[스윙 85점 미달(관망 후보 보존)] {name}({code}): AI 점수 {score:.1f}점 < 기준 85점 (재료등급: {cat_tier_sw})")

            stg = resolve_swing_targets(close_p, regime=regime, market_context=market_context)
            return {
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
                'holding_period': stg['holding_period'] if final_sw_score >= 85 else f"⏸️ AI {final_sw_score}점 (<85점 기준 미달) — 화면 점수 공개용 · 자동매수 관망",
                'score': final_sw_score,
                'reason': " · ".join(reasons),
                'tags': list(dict.fromkeys(tags)),
                'sr_status': sr.get('status', '') if sr else '',
                'support_price': sr.get('support_price', int(ma20)) if sr else int(ma20),
                'next_resistance': sr.get('next_res', '') if sr else '',
                'room_pct': sr.get('room_pct', 5.0) if sr else 5.0,
                'vwap': micro.get('vwap') if micro else int(close_p * 0.99),
                'vwap_diff_pct': micro.get('vwap_diff_pct', 0.0) if micro else 0.0,
                'marcap': int(marcap),
                'marcap_str': marcap_str,
                'is_sub_threshold': final_sw_score < 85,
            }
        except Exception as e:
            logger.debug(f"스윙 후보 분석 예외({code}): {e}")
            return None

    all_swing_evaluated = []
    swing_rows = swing_pool.to_dict('records')
    if swing_rows:
        with ThreadPoolExecutor(max_workers=6) as executor:
            futures = [executor.submit(_evaluate_swing_candidate, r) for r in swing_rows]
            for fut in as_completed(futures):
                try:
                    picked = fut.result()
                    if picked:
                        all_swing_evaluated.append(picked)
                        if picked.get('score', 0) >= 90:
                            swing_picks.append(picked)
                except Exception as e:
                    logger.debug(f"스윙 스레드 결과 처리 예외: {e}")

    if not swing_picks and all_swing_evaluated:
        all_swing_evaluated.sort(key=lambda x: (x['score'], x.get('amount_eok', 0)), reverse=True)
        swing_picks = all_swing_evaluated[:2]
    else:
        swing_picks.sort(key=lambda x: (x['score'], x.get('amount_eok', 0)), reverse=True)
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

        def _eval_pb_candidate(row_dict):
            code = str(row_dict['Code'])
            name = str(row_dict['Name'])
            market = str(row_dict['Market'])
            close_p = float(row_dict['Close'])
            amount_eok = float(row_dict['Amount']) / 1e8
            change_pct = float(row_dict['ChagesRatio'])
            marcap = float(row_dict['Marcap']) if 'Marcap' in row_dict and pd.notnull(row_dict['Marcap']) else 0
            marcap_str = format_marcap(marcap)
            try:
                url = f"https://fchart.stock.naver.com/sise.nhn?symbol={code}&timeframe=day&count=30&requestType=0"
                r = requests.get(url, timeout=2.5)
                if r.status_code != 200 or not r.text:
                    return None
                cleaned = re.sub(r'<\?xml[^>]*\?>', '', r.text).strip()
                root = ET.fromstring(cleaned)
                items = root.findall('.//item')
                if len(items) < 22:
                    return None
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
                    return None

                base_bar, base_gain, days_ago = found_base
                base_mid = (base_bar['open'] + base_bar['close']) / 2.0
                vol_ratio = (today_r['vol'] / base_bar['vol']) * 100 if base_bar['vol'] > 0 else 100.0
                dist_ma5 = abs(close_p - ma5) / close_p * 100
                dist_mid = abs(close_p - base_mid) / close_p * 100

                if close_p >= base_bar['open'] * 0.99 and (dist_ma5 <= 4.5 or dist_mid <= 4.5) and vol_ratio <= 65.0:
                    pb_score = 88 + int(max(0, (65.0 - vol_ratio) * 0.15))
                    support_line = int(round(max(base_bar['open'], min(ma5, base_mid))))
                    return {
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
                    }
            except Exception:
                return None
            return None

        pb_rows = pb_pool.to_dict('records')
        if pb_rows:
            with ThreadPoolExecutor(max_workers=6) as executor:
                for res_pb in executor.map(_eval_pb_candidate, pb_rows):
                    if res_pb:
                        pullback_picks.append(res_pb)
            pullback_picks.sort(key=lambda x: x['score'], reverse=True)
            pullback_picks = pullback_picks[:3]
    except Exception as e:
        logger.debug(f"기준봉 눌림목 스캔 예외: {e}")

    # 스윙 추천주 1~3등(TOP 3)이 대시보드와 텔레그램에 항상 일관되게 표시되도록 보충 및 AI 점수순 정렬 (85점 이상 허용)
    if len(swing_picks) < 3 and pullback_picks:
        existing_sw_codes = {s['code'] for s in swing_picks}
        for pb in pullback_picks:
            if pb.get('score', 0) >= 85 and pb['code'] not in existing_sw_codes:
                swing_picks.append(dict(pb))
                existing_sw_codes.add(pb['code'])
            if len(swing_picks) >= 3:
                break
    swing_picks.sort(key=lambda x: x.get('score', 0), reverse=True)
    swing_picks = swing_picks[:3]

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

    # =========================================================================
    # Track 5: 🎯 내 조건식 ('60일이상추가 1000억') 동일 AI 정밀 채점 (하이브리드: HTS 원본 + 클라우드 폴백)
    # =========================================================================
    condition_picks = []
    condition_meta = {
        'cond_name': '60일이상추가 1000억',
        'source': 'CLOUD_FALLBACK_SCAN',
        'updated_at': datetime.now(timezone(timedelta(hours=9))).strftime('%Y-%m-%d %H:%M:%S'),
        'is_live_hts': False,
    }
    try:
        from pathlib import Path as _Path
        import json as _json
        import requests as _req

        _root_dir = _Path(__file__).resolve().parent.parent
        _cond_cache_path = _root_dir / 'data' / 'kiwoom_condition_cache.json'
        _kst_now = datetime.now(timezone(timedelta(hours=9)))
        _today_str = _kst_now.strftime('%Y-%m-%d')

        _target_items = []  # [{'code': ..., 'name': ...}]
        _hts_cache_valid = False
        if _cond_cache_path.exists():
            try:
                _cdata = _json.loads(_cond_cache_path.read_text(encoding='utf-8'))
                _updated_at = str(_cdata.get('updated_at', ''))
                _cache_date = _updated_at[:10]
                _raw_codes = _cdata.get('codes', []) or []
                _raw_items = _cdata.get('items', []) or []
                _name_map = {str(it.get('code')): str(it.get('name', '')) for it in _raw_items if isinstance(it, dict)}

                # 평일 장중(09:30~23:59)에 오늘자 캐시가 아니면 클라우드 자체 스캔 폴백 가동 (단, 오늘자 0종목 정상 스캔은 유효 처리)
                _hm_int = _kst_now.hour * 100 + _kst_now.minute
                _is_stale_intraday = (_kst_now.weekday() < 5 and 930 <= _hm_int <= 2359 and _cache_date < _today_str)
                if _updated_at and not _is_stale_intraday:
                    _hts_cache_valid = True
                    _target_items = [{'code': str(c), 'name': _name_map.get(str(c), '')} for c in _raw_codes]
                    condition_meta = {
                        'cond_name': str(_cdata.get('cond_name', '60일이상추가 1000억')),
                        'source': str(_cdata.get('source', 'KIWOOM_HTS_WS')),
                        'updated_at': _updated_at,
                        'is_live_hts': True,
                    }
            except Exception as _ce:
                logger.warning(f"키움 조건검색 캐시 로드 예외: {_ce}")

        # 클라우드 임의 폴백(가짜 조건식 생성) 영구 비활성화: 실제 키움 HTS 캐시가 없거나 0종목이면 정직하게 0건 표시
        if not _hts_cache_valid:
            logger.info("[조건검색식] 당일 키움 HTS 실시간 캐시가 없어 가짜 폴백 없이 0건으로 유지합니다.")
            condition_meta['updated_at'] = _kst_now.strftime('%Y-%m-%d %H:%M:%S')
            condition_meta['is_live_hts'] = False
            condition_meta['source'] = 'KIWOOM_HTS_WS_EMPTY'

        # 공통 데이터 프레임 인덱싱 + 누락 종목 네이버 실시간 시세 보완
        _common_map = {}
        if common is not None and not common.empty:
            for _, _crow in common.iterrows():
                _common_map[str(_crow['Code'])] = _crow.to_dict()

        _nh = {'User-Agent': 'Mozilla/5.0'}
        _closing_code_set = {p['code'] for p in closing_picks}
        _swing_code_set = {p['code'] for p in swing_picks}

        for _item in _target_items:
            _code = str(_item['code']).strip()
            if not _code:
                continue
            _row = dict(_common_map.get(_code, {}))
            _name = str(_row.get('Name') or _item.get('name') or _code)
            _market = str(_row.get('Market') or 'KRX')
            _close_p = float(_row.get('Close') or 0)
            _open_p = float(_row.get('Open') or 0)
            _high_p = float(_row.get('High') or 0)
            _low_p = float(_row.get('Low') or 0)
            _chg_pct = float(_row.get('ChagesRatio') or 0)
            _amount_won = float(_row.get('Amount') or 0)
            _marcap = float(_row.get('Marcap') or 0)

            # 누락되었거나 OHLC 미보정(Open==Close==High==Low) 종목 실시간 보정
            if _close_p <= 0 or (_open_p == _close_p == _high_p == _low_p):
                try:
                    _pr = _req.get(f'https://m.stock.naver.com/api/stock/{_code}/price?pageSize=1&page=1', headers=_nh, timeout=4)
                    if _pr.status_code == 200:
                        _pd_list = _pr.json()
                        if isinstance(_pd_list, list) and _pd_list:
                            _pd = _pd_list[0]
                            _close_p = float(str(_pd.get('closePrice', _close_p)).replace(',', '') or _close_p)
                            _open_p = float(str(_pd.get('openPrice', _close_p)).replace(',', '') or _close_p)
                            _high_p = float(str(_pd.get('highPrice', _close_p)).replace(',', '') or _close_p)
                            _low_p = float(str(_pd.get('lowPrice', _close_p)).replace(',', '') or _close_p)
                            _chg_pct = float(str(_pd.get('fluctuationsRatio', _chg_pct)).replace(',', '') or _chg_pct)
                            _vol_raw = float(str(_pd.get('accumulatedTradingVolume', 0)).replace(',', '') or 0)
                            if _amount_won <= 0 and _vol_raw > 0 and _close_p > 0:
                                _amount_won = _vol_raw * _close_p
                except Exception:
                    pass
                try:
                    _br = _req.get(f'https://m.stock.naver.com/api/stock/{_code}/basic', headers=_nh, timeout=4)
                    if _br.status_code == 200:
                        _bd = _br.json()
                        if _bd.get('stockName'):
                            _name = str(_bd['stockName'])
                        _mkt_ex = (_bd.get('stockExchangeType') or {}).get('name')
                        if _mkt_ex:
                            _market = str(_mkt_ex)
                        if _close_p <= 0 and _bd.get('closePrice'):
                            _close_p = float(str(_bd.get('closePrice')).replace(',', '') or 0)
                        if _chg_pct == 0 and _bd.get('fluctuationsRatio'):
                            _chg_pct = float(str(_bd.get('fluctuationsRatio')).replace(',', '') or 0)
                except Exception:
                    pass
                if _marcap <= 0:
                    try:
                        _ir = _req.get(f'https://m.stock.naver.com/api/stock/{_code}/integration', headers=_nh, timeout=4)
                        if _ir.status_code == 200:
                            for _ti in (_ir.json().get('totalInfos') or []):
                                if _ti.get('code') == 'marketValue':
                                    _mv_s = str(_ti.get('value', '')).replace(',', '')
                                    _jo_m = re.search(r'(\d+)조', _mv_s)
                                    _ek_m = re.search(r'(\d+)억', _mv_s)
                                    _mc_e = (int(_jo_m.group(1)) * 10000 if _jo_m else 0) + (int(_ek_m.group(1)) if _ek_m else 0)
                                    if _mc_e > 0:
                                        _marcap = float(_mc_e * 1e8)
                                    break
                    except Exception:
                        pass

            if _close_p <= 0:
                continue

            _amount_eok = _amount_won / 1e8
            _marcap_str = format_marcap(_marcap)
            _head_ratio = (_high_p - _close_p) / (_high_p - _low_p) if _high_p > _low_p else 0.0
            _sr = analyze_support_resistance(_code, _name)
            _sr_score = _sr.get('sr_score', 0.0) if _sr else 0.0
            _sr_status = _sr.get('status', '60일 추세 돌파 스캔') if _sr else '60일 추세 돌파 스캔'
            _support_price = _sr.get('support_price', int(_close_p * 0.98)) if _sr else int(_close_p * 0.98)
            _next_res = _sr.get('next_res', f"{int(_close_p * 1.05):,}원") if _sr else f"{int(_close_p * 1.05):,}원"
            _room_pct = _sr.get('room_pct', 5.0) if _sr else 5.0
            _sr_tags = _sr.get('tags', []) if _sr else []
            _rvol = _sr.get('rvol', 1.5) if _sr else 1.5
            _disp5_pct = _sr.get('disp5_pct', 0.0) if _sr else 0.0
            _turnover_pct = round((_amount_eok / (_marcap / 1e8)) * 100, 2) if _marcap > 0 else 0.0
            _stock_sec = get_stock_sector(_code)
            _micro = analyze_intraday_microstructure(_code, _close_p)
            _major_flow = fetch_stock_major_flow(_code, toxic_lookback_days=7)

            # 종가베팅과 100% 동일한 [정석 B: 기본 40점 고정 + 핵심 실력 55점 + 알파 보너스 20점 → 99점 상한] 적용
            _abs_vol_score = min((_amount_eok / 500.0) * 13.0, 13.0)
            _turn_req_pct = 0.5 if _marcap >= 50000 * 1e8 else 3.0
            _turnover_score = min((_turnover_pct / _turn_req_pct) * 5.0, 5.0)
            _sr_weighted = 14.0 if _sr_score >= 25.0 else (12.0 if _sr_score >= 15.0 else (9.0 if _sr_score > 0 else 0.0))
            _candle_score = max(0.0, (1.0 - _head_ratio) * 8.0)
            _score = 40.0 + _abs_vol_score + _turnover_score + _sr_weighted + _candle_score

            _reasons = [
                f"🎯 조건식('60일이상추가 1000억') 포착",
                f"거래대금 {int(_amount_eok):,}억(시총회전율 {_turnover_pct:.1f}%)",
                f"캔들 완성도(윗꼬리 {int(_head_ratio*100)}%)"
            ]
            if _sr_status:
                _reasons.append(f"차트: {_sr_status}")
            if _rvol > 1.0:
                _score += min(((_rvol - 1.0) / 1.2) * 4.0, 4.0)
                if _rvol >= 2.0:
                    _reasons.append(f"상대거래량 RVOL {_rvol:.1f}배")
            if _micro:
                _vwap_diff = _micro.get('vwap_diff_pct', 0.0)
                _peak_t = _micro.get('peak_time', '')
                _auc_diff = _micro.get('closing_auction_diff', 0.0)
                if _vwap_diff >= 0:
                    _score += 4.0
                    _reasons.append(f"당일 VWAP 상회(+{_vwap_diff:.1f}% · 고점 {_peak_t})")
                if _auc_diff >= 0.3:
                    _score += 2.0
                    _reasons.append(f"막판 동시호가 유입(+{_auc_diff:.2f}%)")
                if _micro.get('is_morning_dump'):
                    _score -= 6.0
                    _reasons.append(f"⚠️ 오전 고점({_peak_t}) 대비 VWAP 하회(-6점)")
            _sec_bonus = 0.0
            if _stock_sec in hot_sector_names:
                _sec_bonus += 4.0
                _reasons.append(f"🔥주도섹터({_stock_sec}) 동조화")
            _leader_or_confirm = False
            if _code in hot_leader_codes:
                _leader_or_confirm = True
                _reasons.append("👑주도섹터 1등 대장주")
            if _stock_sec in winning_sectors:
                _leader_or_confirm = True
                _reasons.append("🧠고승률 섹터")

            _tags = ['HTS조건식', '60일1000억'] + _sr_tags
            if _code in _closing_code_set:
                _leader_or_confirm = True
                _reasons.append("👑AI 종가베팅 동시 포착(더블컨펌)")
                _tags.insert(0, "👑종가더블컨펌")
            elif _code in _swing_code_set:
                _leader_or_confirm = True
                _reasons.append("🌊AI 스윙 동시 포착(더블컨펌)")
                _tags.insert(0, "🌊스윙더블컨펌")
            if _leader_or_confirm:
                _sec_bonus += 4.0
            _score += min(_sec_bonus, 8.0)

            if _head_ratio > 0.38:
                _score -= 6.0
                _reasons.append(f"⚠️ 윗꼬리 과다({int(_head_ratio*100)}% > 38%) 주의(-6점)")
                _tags.append("⚠️윗꼬리주의")
            if _major_flow.get('toxic_disclosure'):
                _score -= 15.0
                _reasons.append(f"🚨 악재 공시 감지({_major_flow['toxic_disclosure']})")
                _tags.append("🚨악재공시주의")
            if _major_flow.get('is_dual_buy'):
                _score += 7.0
                _reasons.append("🏦외인·기관 쌍끌이 수급(+7점)")
                _tags.append("쌍끌이수급")
            elif _major_flow.get('is_organ_accum'):
                _score += 5.5
                _reasons.append("🏦기관 연속 순매수(+5.5점)")
                _tags.append("기관매집")
            elif _major_flow.get('is_major_dump'):
                _score -= 5.0
                _reasons.append("⚠️최근 3일 외인·기관 순매도(-5점)")
            else:
                _score += 2.0

            _cat_info = fetch_stock_catalyst(_code, _name, _stock_sec)
            _cat_tier = _cat_info.get('tier', 'B')
            if _code in catalyst_codes and _cat_tier not in ('S+', 'S', 'C', 'F'):
                _cat_tier = 'S'
                _cat_info['tier_label'] = '🟢S급 DART 공시 호재(+8점)'
            _cat_weight_map = {'S+': 10.0, 'S': 8.0, 'A': 5.0, 'B': 0.0, 'C': -8.0, 'F': -20.0}
            _cat_score = _cat_weight_map.get(_cat_tier, 0.0)
            _ev_info = event_boost_map.get(_name) or event_boost_map.get(_code)
            if _ev_info and _ev_info.get('boost_score', 0) > 0 and _cat_tier not in ('C', 'F'):
                _cat_score = min(10.0, _cat_score + 2.0)
                _reasons.append(f"🎯{_ev_info.get('tag')} (호재모멘텀)")
                _tags.append("D-Day호재모멘텀")
            _score += _cat_score
            if _cat_tier != 'B':
                _reasons.append(_cat_info.get('tier_label', f"뉴스·공시({_cat_tier}등급 {_cat_score:+.0f}점)"))
                if _cat_tier in ('S+', 'S'):
                    _tags.append("실적/공시호재")
                elif _cat_score < 0:
                    _tags.append("⚠️재료소멸주의")

            _disp20_pct = _sr.get('disp20_pct', 0.0) if _sr else 0.0
            _disp60_pct = _sr.get('disp60_pct', 0.0) if _sr else 0.0
            _chg_5d_pct = _sr.get('chg_5d_pct', 0.0) if _sr else 0.0
            _cond_overheat = []
            if _disp20_pct > 28.0:
                _cond_overheat.append(f"20일선+{_disp20_pct:.1f}%")
            if _disp60_pct > 50.0:
                _cond_overheat.append(f"60일선+{_disp60_pct:.1f}%")
            if _chg_5d_pct > 35.0:
                _cond_overheat.append(f"5일누적+{_chg_5d_pct:.1f}%")
            if _cond_overheat:
                _score -= 10.0
                _reasons.append(f"⚠️이격과열상투({', '.join(_cond_overheat)})")

            if _major_flow.get('toxic_disclosure') or _cat_tier == 'F':
                _score = min(_score, 74.0)
            elif _head_ratio > 0.38:
                _score = min(_score, 79.0)
            elif _cond_overheat:
                _score = min(_score, 84.0)

            _score = max(0.0, min(_score, 99.0))
            _hp_str = "HTS 조건식 포착 → AI 90점+ 시 종가/스윙 분할 매수, 90점 미만 시 관망"

            condition_picks.append({
                'code': _code,
                'name': _name,
                'market': _market,
                'sector': _stock_sec,
                'price': int(_close_p),
                'change_pct': round(_chg_pct, 2),
                'amount_eok': int(_amount_eok),
                'target_1': int(_close_p * 1.02),
                'target_1_pct': '+2.0%',
                'target_2': int(_close_p * 1.05),
                'target_2_pct': '+5.0%',
                'stop_loss': int(_close_p * 0.98),
                'stop_loss_pct': '-2.0%',
                'holding_period': _hp_str,
                'score': int(round(_score)),
                'reason': " · ".join(_reasons),
                'tags': _tags,
                'sr_status': _sr_status,
                'support_price': _support_price,
                'next_resistance': _next_res,
                'room_pct': _room_pct,
                'marcap': int(_marcap),
                'marcap_str': _marcap_str,
                'rvol': _rvol,
                'turnover_pct': _turnover_pct,
                'vwap': _micro.get('vwap') if _micro else int(_close_p * 0.99),
                'vwap_diff_pct': _micro.get('vwap_diff_pct', 0.0) if _micro else 0.0,
                'peak_time': _micro.get('peak_time', '15:15') if _micro else '15:15',
                'closing_auction_diff': _micro.get('closing_auction_diff', 0.0) if _micro else 0.0,
                'is_breakout': bool(_sr and (_sr.get('is_20_breakout') or _sr.get('is_60_breakout'))),
            })

        condition_picks.sort(key=lambda x: x['score'], reverse=True)
    except Exception as _cond_err:
        logger.warning(f"조건검색식('60일이상추가 1000억') AI 평가 예외: {_cond_err}")

    for p in (closing_picks + swing_picks + breakout_picks + pullback_picks + condition_picks):
        if 'turnover_pct' not in p:
            mc = p.get('marcap', 0)
            p['turnover_pct'] = round((p.get('amount_eok', 0) / (mc / 1e8)) * 100, 2) if mc > 0 else 0.0
        p['nxt_info'] = fetch_nxt_over_market_info(p['code'])
        p['sector'] = get_stock_sector(p['code'])
        cat_info = fetch_stock_catalyst(p['code'], p.get('name', ''), p['sector'])
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

    # [STEP 4] 익일 시초가 성과 자동 추적을 위한 당일 종가베팅 및 스윙 종목 기록 (리스크 차단/관망 후보도 사후 검증용 등록)
    try:
        try:
            from src.track_record import record_closing_picks
        except ImportError:
            from track_record import record_closing_picks
        record_closing_picks(closing_picks, risk_score=risk_val, is_blocked=(risk_val > 60))
    except Exception as e:
        logger.warning(f"종가베팅 트랙 레코드 기록 실패: {e}")

    try:
        try:
            from src.swing_track_record import record_swing_picks
        except ImportError:
            from swing_track_record import record_swing_picks
        record_swing_picks(swing_picks, risk_score=risk_val, is_blocked=(risk_val > 60))
    except Exception as e:
        logger.warning(f"스윙 트랙 레코드 기록 실패: {e}")

    res = {
        'regime': regime,
        'closing': closing_picks,
        'swing': swing_picks,
        'swing_regime': resolve_swing_targets(10000, regime=regime, market_context=market_context),
        'breakout': breakout_picks,
        'pullback': pullback_picks,
        'condition': condition_picks,
        'condition_meta': condition_meta,
        'hot_sectors': hot_sectors,
        'breadth_pct': breadth_pct,
        'event_intelligence': event_intel,
    }
    _RECOMMENDATIONS_CACHE = res
    return res


def get_fallback_recommendations():
    return {"regime": {"status": "neutral", "badge": "정밀 선별", "badge_class": "regime-neutral", "message": "원칙 준수", "position_advice": "현금 관망"}, "closing": [], "swing": [], "breakout": [], "pullback": [], "condition": [], "condition_meta": {}, "hot_sectors": []}
