"""
AI 실시간 시장 리스크 스코어 모듈 v2.0 (Institutional Quant Risk Engine)

[산출 원리 & 9대 팩터 황금 가중치 기준 (총 100점 만점 — 국내 실전 53% : 글로벌 선행 47%)]
국내 수급·내부체력 지표(53%)와 글로벌 선행 지표(47%)를 결합하여,
0점(극단적 안정/강세장) ~ 100점(극단적 패닉/폭락장)의 복합 위험도를 정밀 산출합니다.

1. 미국 E-mini 나스닥100 선물 실시간 등락률 (25% 가중치 — 단독 1위 선행지표):
   - 익일 09:00 시초가 갭(Gap) 선행성을 반영하되, 15:20(미국 새벽 1시) 얇은 호가 노이즈 과민반응을 방지한 최적 비중
2. 국내 코스피(10%) & 코스닥(8%) 지수 등락률 (18% 가중치):
   - 당일 국내 증시 실제 마감 추세 및 하방 압력 측정
3. 국내 코스피·코스닥 외국인 + 기관 메이저 합산 수급 (15% 가중치 — 신규):
   - 지수가 상승해도 외인·기관이 대량 매도(개인 떠넘기기)하면 익일 시초가 갭하락 위험이 급증하므로 메이저 수급 반영
4. 장중 지수 윗꼬리(전강후약 투매 감지, 6%) & 상승종목 비율 Breadth (6%) (12% 가중치 — 신규):
   - 당일 고점 대비 오후장 밀림 폭(지수 윗꼬리)과 전체 종목 중 상승 종목 비율(착시 장세 필터링) 반영
5. 필라델피아 반도체 지수 등락률 (10% 가중치):
   - 국내 대표 섹터(반도체/IT) 투자심리 선행 지표 (나스닥 선물 25%와 중복을 피하기 위해 10% 배정)
6. 원/달러 환율 등락률 + 고환율 절대 레벨 (8% 가중치):
   - 환율 급등 속도(6%) 및 1,400원대 고환율 레벨 부담(2%) 동시 반영
7. VIX 변동성 지수 (5% 가중치):
   - 미국 S&P500 옵션 시장 공포 수치
8. 미국 10년물 국채금리 일간 변동폭 (4% 가중치):
   - 금리 급등에 따른 성장주 밸류에이션 하방 압력
9. CNN Fear & Greed Index (3% 가중치):
   - 글로벌 중기 투자자 심리 배경 상태
"""
import functools
import logging
import re
import xml.etree.ElementTree as ET
import requests

logger = logging.getLogger(__name__)


def clamp(value: float, min_val: float = 0.0, max_val: float = 1.0) -> float:
    """값을 [min_val, max_val] 범위로 제한"""
    return max(min_val, min(max_val, value))


@functools.lru_cache(maxsize=8)
def fetch_index_intraday_pullback(symbol: str = "KOSPI") -> float:
    """
    네이버 일봉 차트 API에서 당일 지수의 '고점 대비 현재가 밀림 폭(%p, 지수 윗꼬리)'을 계산.
    - 전약후강(당일 최고가 마감): 0.0%p
    - 전강후약(장중 +2.5% 찍고 +0.5%로 밀림): ~2.0%p
    """
    try:
        url = f"https://fchart.stock.naver.com/sise.nhn?symbol={symbol}&timeframe=day&count=2&requestType=0"
        r = requests.get(url, timeout=3)
        if r.status_code != 200 or not r.text:
            return 0.0
        cleaned = re.sub(r'<\?xml[^>]*\?>', '', r.text).strip()
        root = ET.fromstring(cleaned)
        items = root.findall('.//item')
        if len(items) < 2:
            return 0.0
        prev_parts = items[-2].attrib['data'].split('|')
        curr_parts = items[-1].attrib['data'].split('|')
        prev_close = float(prev_parts[4])
        curr_high = float(curr_parts[2])
        curr_close = float(curr_parts[4])
        if prev_close <= 0 or curr_high <= curr_close:
            return 0.0
        # 당일 고점 수익률(%p) - 현재 종가 수익률(%p) = 고점 대비 밀린 폭(%p)
        pullback_pctp = ((curr_high - curr_close) / prev_close) * 100.0
        return round(max(0.0, pullback_pctp), 2)
    except Exception as e:
        logger.debug(f"{symbol} 장중 윗꼬리 계산 실패: {e}")
        return 0.0


def compute_risk_score(context: dict) -> int:
    """
    시장 컨텍스트 딕셔너리로부터 0~100점의 위험도 점수를 산출
    (0점: 매우 안정/호황 ~ 100점: 극단적 패닉/폭락장)
    """
    fut_ratio = float(context.get('fut_ratio', 0.0) or 0.0)
    sox_ratio = float(context.get('sox_ratio', 0.0) or 0.0)
    kp_ratio = float(context.get('kp_ratio', 0.0) or 0.0)
    kd_ratio = float(context.get('kd_ratio', 0.0) or 0.0)
    fx_ratio = float(context.get('fx_ratio', 0.0) or 0.0)
    fx_close_raw = context.get('fx_close', 1350.0)
    try:
        fx_level = float(str(fx_close_raw).replace(',', '').strip() or 1350.0)
    except Exception:
        fx_level = 1350.0

    cnn_score = float(context.get('cnn_score', 50.0) or 50.0)
    vix = float(context.get('vix', 18.0) or 18.0)
    us10y_diff = float(context.get('us10y', 0.0) or 0.0)

    # 국내 외국인·기관 수급 (단위: 억 원)
    kp_for = float(context.get('kp_for_num', 0.0) or 0.0)
    kp_inst = float(context.get('kp_inst_num', 0.0) or 0.0)
    kd_for = float(context.get('kd_for_num', 0.0) or 0.0)
    kd_inst = float(context.get('kd_inst_num', 0.0) or 0.0)
    total_major_eok = kp_for + kp_inst + kd_for + kd_inst

    # 1. 미국 E-mini 나스닥100 선물 위험도 (25점 만점 — 기준: -1.5% 이하 시 1.0, +1.5% 이상 시 0.0)
    fut_risk = clamp(0.5 - (fut_ratio / 3.0)) * 25.0

    # 2. 필라델피아 반도체 지수 위험도 (10점 만점 — 기준: -2.5% 이하 시 1.0, +2.5% 이상 시 0.0)
    sox_risk = clamp(0.5 - (sox_ratio / 5.0)) * 10.0

    # 3. 국내 코스피·코스닥 외국인+기관 메이저 합산 수급 위험도 (15점 만점)
    #    합산 +4,000억 이상 순매수 시 0.0 (최고 안전), -4,000억 이하 순매도 시 1.0 (최고 위험)
    major_flow_risk = clamp(0.5 - (total_major_eok / 8000.0)) * 15.0

    # 4. 코스피(10점) & 코스닥(8점) 지수 등락률 위험도 (18점 만점 — 기준: -2.0% 이하 시 1.0, +2.0% 이상 시 0.0)
    kp_risk = clamp(0.5 - (kp_ratio / 4.0)) * 10.0
    kd_risk = clamp(0.5 - (kd_ratio / 4.0)) * 8.0

    # 5. 장중 지수 윗꼬리(전강후약 투매 감지, 6점) & 시장 상승종목 비율 Breadth (6점) (합 12점 만점)
    kp_pullback = context.get('kp_pullback_pctp')
    kd_pullback = context.get('kd_pullback_pctp')
    if kp_pullback is None:
        kp_pullback = fetch_index_intraday_pullback("KOSPI")
    if kd_pullback is None:
        kd_pullback = fetch_index_intraday_pullback("KOSDAQ")
    avg_pullback = (float(kp_pullback) * 0.55) + (float(kd_pullback) * 0.45)
    # 고점 대비 밀림 폭이 0.2%p 이하면 0점(전약후강 고가마감), 1.8%p 이상 밀리면 6점 만점(전강후약 투매)
    intraday_tail_risk = clamp((avg_pullback - 0.2) / 1.6) * 6.0

    # 시장 상승종목 비율 (Breadth %: 기본 50%, 65% 이상이면 0점, 30% 이하면 6점 만점)
    breadth_pct = float(context.get('breadth_pct', 50.0) or 50.0)
    breadth_risk = clamp((65.0 - breadth_pct) / 35.0) * 6.0

    # 6. 원/달러 환율 위험도 (8점 만점 = 등락 속도 6점 + 고환율 레벨 2점)
    fx_chg_risk = clamp(0.5 + (fx_ratio / 2.0)) * 6.0
    fx_lvl_risk = clamp((fx_level - 1330.0) / 100.0) * 2.0
    fx_risk = fx_chg_risk + fx_lvl_risk

    # 7. VIX 변동성 위험도 (5점 만점 — 12 이하 0.0, 35 이상 1.0)
    vix_risk = clamp((vix - 12.0) / 23.0) * 5.0

    # 8. 미국 10년물 국채금리 변동 위험도 (4점 만점 — +0.08%p 급등 시 1.0, -0.08%p 급락 시 0.0)
    us10y_risk = clamp(0.5 + (us10y_diff / 0.16)) * 4.0

    # 9. CNN 공포탐욕 위험도 (3점 만점 — 0점 극단공포 -> 1.0, 100점 극단탐욕 -> 0.0)
    cnn_risk = clamp((100.0 - cnn_score) / 100.0) * 3.0

    total_score = (
        fut_risk
        + sox_risk
        + major_flow_risk
        + kp_risk
        + kd_risk
        + intraday_tail_risk
        + breadth_risk
        + fx_risk
        + vix_risk
        + us10y_risk
        + cnn_risk
    )
    clamped_score = int(round(clamp(total_score, 0.0, 100.0)))
    return clamped_score


def get_risk_assessment(score: int) -> dict:
    """점수별 상세 진단 및 행동 지침 반환"""
    if score < 35:
        return {
            'score': score,
            'grade': '안정 (저위험)',
            'color': '#10b981',
            'badge_class': 'risk-good',
            'desc': '시장 위험도 낮음: 공격적 매매 및 종가베팅 비중 100% 정상 운용 가능 (상승 우세 장세)'
        }
    elif score <= 65:
        return {
            'score': score,
            'grade': '주의 (중위험)',
            'color': '#f59e0b',
            'badge_class': 'risk-caution',
            'desc': '단기 변동성 주의: 리스크 점수 비례 비중 축소 및 기계적 익절 원칙 엄격 준수 (박스권/혼조세)'
        }
    else:
        return {
            'score': score,
            'grade': '경고 (고위험)',
            'color': '#ef4444',
            'badge_class': 'risk-danger',
            'desc': '시장 하방 압력 경계 (65점 초과): 신규 매수 전면 차단 및 현금 100% 안전 보존'
        }
