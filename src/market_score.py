"""
종가베팅 & 시초가 매도 타이밍 전문 시황 분석 모듈 (KRX + Nextrade 대체거래소 반영)
1. [아침 07:40] 🌅 08:00 NXT 프리마켓 개장 전 시초가 매도 가이드
2. [아침 08:40] 🌅 09:00 정규장 개장 전 최종 매도 & 동시호가 가이드
3. [오후 15:10] 🎯 15:30 정규장 마감 1차 종가베팅 가이드
4. [저녁 19:40] 🎯 20:00 NXT 8시 마감 최종 종가베팅 가이드
"""
import functools
import logging
from datetime import datetime, timezone, timedelta
import requests

logger = logging.getLogger(__name__)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
}

KST = timezone(timedelta(hours=9))


@functools.lru_cache(maxsize=32)
def fetch_nasdaq_futures():
    """실시간 미국 E-mini 나스닥 100 선물 (NQ=F) 조회"""
    url = 'https://query1.finance.yahoo.com/v8/finance/chart/NQ%3DF?interval=1d'
    try:
        r = requests.get(url, headers=HEADERS, timeout=8).json()
        meta = r['chart']['result'][0]['meta']
        price = meta.get('regularMarketPrice')
        prev = meta.get('chartPreviousClose')
        ratio = ((price - prev) / prev) * 100 if prev else 0.0
        return price, ratio
    except Exception as e:
        logger.warning(f"나스닥 선물 조회 실패: {e}")
    return None, 0.0


@functools.lru_cache(maxsize=32)
def fetch_naver_index(code):
    """네이버 증권 글로벌/국내 인덱스 조회 (예: .IXIC, .SOX, .GDAXI)"""
    url = f'https://api.stock.naver.com/index/{code}/basic'
    try:
        r = requests.get(url, headers=HEADERS, timeout=8).json()
        close = r.get('closePrice', '')
        ratio = float(r.get('fluctuationsRatio', 0))
        return close, ratio
    except Exception as e:
        logger.warning(f"인덱스 {code} 조회 실패: {e}")
    return '', 0.0


@functools.lru_cache(maxsize=32)
def fetch_usdkrw():
    """원/달러 환율 및 등락률 조회"""
    url = 'https://api.stock.naver.com/marketindex/exchange/FX_USDKRW'
    try:
        r = requests.get(url, headers=HEADERS, timeout=8).json()
        ex = r.get('exchangeInfo', {})
        close = ex.get('closePrice', '')
        ratio = float(ex.get('fluctuationsRatio', 0))
        diff = float(ex.get('changeValue', 0))
        return close, ratio, diff
    except Exception as e:
        logger.warning(f"환율 조회 실패: {e}")
    return '', 0.0, 0.0


@functools.lru_cache(maxsize=32)
def fetch_cnn_fear_greed():
    """CNN Fear & Greed Index 조회 (0~100)"""
    url = 'https://production.dataviz.cnn.io/index/fearandgreed/graphdata'
    try:
        r = requests.get(url, headers=HEADERS, timeout=8)
        if r.status_code == 200:
            fg = r.json().get('fear_and_greed', {})
            return float(fg.get('score', 50)), fg.get('rating', 'neutral')
    except Exception as e:
        logger.warning(f"CNN Fear & Greed 조회 실패: {e}")
    return 50.0, 'neutral'


@functools.lru_cache(maxsize=32)
def fetch_kr_market(code):
    """코스피/코스닥 지수 및 외인/기관 순매매 금액(억원) 조회"""
    close, ratio = '', 0.0
    foreign_str, inst_str = '0', '0'
    foreign_num, inst_num = 0, 0
    try:
        b = requests.get(f'https://m.stock.naver.com/api/index/{code}/basic', headers=HEADERS, timeout=8).json()
        close = b.get('closePrice', '')
        ratio = float(b.get('fluctuationsRatio', 0))
    except Exception as e:
        logger.warning(f"{code} 기본 정보 조회 실패: {e}")

    try:
        t = requests.get(f'https://m.stock.naver.com/api/index/{code}/trend', headers=HEADERS, timeout=8).json()
        foreign_str = t.get('foreignValue', '0')
        inst_str = t.get('institutionalValue', '0')
        foreign_num = int(foreign_str.replace(',', '').replace('+', '')) if foreign_str else 0
        inst_num = int(inst_str.replace(',', '').replace('+', '')) if inst_str else 0
    except Exception as e:
        logger.warning(f"{code} 수급 정보 조회 실패: {e}")

    return close, ratio, foreign_str, inst_str, foreign_num, inst_num


DASHBOARD_URL = "https://parkseungbin1.github.io/binistock/"


def fetch_vix():
    """VIX 공포/변동성 지수 조회 (.VIX)"""
    return fetch_naver_index('.VIX')


@functools.lru_cache(maxsize=32)
def fetch_us10y():
    """미국 10년물 국채금리 조회 (^TNX)"""
    url = 'https://query1.finance.yahoo.com/v8/finance/chart/%5ETNX?interval=1d'
    try:
        r = requests.get(url, headers=HEADERS, timeout=8).json()
        meta = r['chart']['result'][0]['meta']
        price = meta.get('regularMarketPrice')
        prev = meta.get('chartPreviousClose')
        diff = price - prev if (price is not None and prev is not None) else 0.0
        return price, diff
    except Exception as e:
        logger.warning(f"미국 10년물 국채금리 조회 실패: {e}")
    return None, 0.0


def make_gauge_bar(score, total_blocks=10):
    """0~100점 점수를 게이지 바로 변환"""
    filled = min(max(round(score / (100 / total_blocks)), 0), total_blocks)
    return '■' * filled + '░' * (total_blocks - filled)


# ==========================================================
# 1 & 2. [아침 07:40 / 08:40] 시초가 매도 타이밍 & 대응 가이드
# ==========================================================
def get_morning_sell_guide(time_label="07:40", is_nxt=True):
    nas_close, nas_ratio = fetch_naver_index('.IXIC')
    sox_close, sox_ratio = fetch_naver_index('.SOX')
    fut_price, fut_ratio = fetch_nasdaq_futures()
    fx_close, fx_ratio, _ = fetch_usdkrw()
    cnn_score, cnn_rating = fetch_cnn_fear_greed()
    vix_close, vix_ratio = fetch_vix()
    us10y_price, us10y_diff = fetch_us10y()

    # 시초가 갭 예측 점수 (0~100점)
    score = 50.0
    score += (nas_ratio * 12) * 0.30
    score += (sox_ratio * 12) * 0.25
    score += (fut_ratio * 15) * 0.30
    score -= (fx_ratio * 15) * 0.15
    if vix_close:
        try:
            v_val = float(str(vix_close).replace(',', ''))
            if v_val > 22.0:
                score -= min((v_val - 22.0) * 1.5, 15)
        except Exception:
            pass
    score = min(max(round(score), 0), 100)
    gauge = make_gauge_bar(score)

    target_text = "08:00 NXT 프리마켓" if is_nxt else "09:00 정규장"

    if score >= 75:
        core_action = "🔥 시초 갭상승 슈팅 시 적극 분할 익절 (50~70%)"
        status_label = "강한 갭상승 출발 예상 (적극 익절)"
        icon = "🟢"
        guide = (
            f"• <b>매도 타이밍</b>: 개장 직후 5~10분간 시초 갭을 띄울 때 욕심부리지 말고 보유 물량의 <b>50~70%를 1차 익절</b>하세요.\n"
            f"• <b>홀딩 기준</b>: 잔여 물량은 '시초가'를 손절선(본절스탑)으로 잡고 상방 추세를 추종하세요."
        )
    elif score >= 55:
        core_action = "📈 수급 유입 확인 후 +2~4% 구간 분할 익절"
        status_label = "완만한 상승/보합 출발 (슈팅 시 분할 익절)"
        icon = "🟢"
        guide = (
            f"• <b>매도 타이밍</b>: 개장 직후 체결강도와 수급 유입을 확인한 뒤 <b>+2~+4% 구간에서 분할 익절</b>을 시작하세요.\n"
            f"• <b>주의점</b>: 거래량이 줄며 시초가를 깨는 흐름이 나오면 미련 없이 남은 물량을 본절/약익절로 정리하세요."
        )
    elif score >= 40:
        core_action = "⚖️ 뇌동매매 금지 & 전일 종가 지지선 본절 방어"
        status_label = "혼조/보합 출발 (개장 초 수급 확인 필수)"
        icon = "🟡"
        guide = (
            f"• <b>매도 타이밍</b>: 개장 정각에 섣불리 던지지 마시고, 첫 5분간 메이저 수급 방향을 지켜보세요.\n"
            f"• <b>원칙</b>: 전일 종가를 지지하면 1~2% 짧은 반등에 익절하고, 전일 종가를 하향 이탈하면 즉시 비중을 줄이세요."
        )
    else:
        core_action = "🔴 시초가 패닉셀 금지! 10~20분 첫 반등 시 매도"
        status_label = "갭하락 출발 우려 (투매 동참 금지, 반등 매도)"
        icon = "🔴"
        guide = (
            f"• <b>매도 타이밍</b>: 개장 직후 공포에 동참해 최저점에 던지지 마세요. 통상 개장 후 10~20분경 나오는 <b>'첫 기술적 반등 파동'</b>에서 비중을 축소하거나 분할 정리하는 것이 유리합니다.\n"
            f"• <b>원칙</b>: 시초 갭하락 음봉 시 무리한 물타기 절대 금지, 현금 비중 우선 확보."
        )

    title_desc = "08:00 NXT 프리마켓 개장 전" if is_nxt else "09:00 정규장 개장 전 최종"

    def arr(r):
        return '🔺' if r > 0 else ('🔻' if r < 0 else '➖')

    nas_str = f"🇺🇸 나스닥: <b>{nas_close}</b> ({nas_ratio:+.2f}%) {arr(nas_ratio)}" if nas_close else ""
    sox_str = f"💻 반도체: <b>{sox_close}</b> ({sox_ratio:+.2f}%) {arr(sox_ratio)}" if sox_close else ""
    fut_str = f"🇺🇸 NQ선물: <b>{fut_price:,.1f}</b> ({fut_ratio:+.2f}%) {arr(fut_ratio)}" if fut_price else ""
    fx_desc = '원화 강세' if fx_ratio < 0 else '원화 약세'
    fx_str = f"💱 환율: <b>{fx_close}원</b> ({fx_desc})" if fx_close else ""
    vix_str = f"🌪️ VIX: <b>{vix_close}</b> ({vix_ratio:+.2f}%)" if vix_close else ""
    us10y_str = f"📈 美10년물: <b>{us10y_price:.2f}%</b> ({us10y_diff:+.2f}%p)" if us10y_price else ""

    target_title = "08:00 NXT 프리마켓 시초가 매도 가이드" if is_nxt else "09:00 정규장 최종 시초가 매도 가이드"

    now_kst = datetime.now(KST)
    ko_wd = ['월', '화', '수', '목', '금', '토', '일'][now_kst.weekday()]
    date_str = f"{now_kst.strftime('%m/%d')}({ko_wd})"
    msg = f"🌅 <b>[{target_title}]</b> ({date_str} {time_label} 알림)\n"
    msg += "━━━━━━━━━━━━━━━━━━━━\n"
    msg += f"🎯 <b>핵심 전략</b>: <b>{core_action}</b>\n"
    msg += f"📊 <b>시장 점수</b>: <b>{score}점</b> [{gauge}] {icon} | <b>{status_label}</b>\n"
    msg += "━━━━━━━━━━━━━━━━━━━━\n\n"

    msg += "⚡ <b>10초 글로벌 팩트 체크</b>\n"
    if nas_str and sox_str:
        msg += f"• {nas_str} | {sox_str}\n"
    elif nas_str:
        msg += f"• {nas_str}\n"
    if fut_str and fx_str:
        msg += f"• {fut_str} | {fx_str}\n"
    elif fut_str:
        msg += f"• {fut_str}\n"
    if vix_str and us10y_str:
        msg += f"• {vix_str} | {us10y_str}\n"
    elif vix_str:
        msg += f"• {vix_str}\n"
    msg += f"• 🧭 CNN 심리: <b>{cnn_score:.0f}점</b> ({cnn_rating.upper()})\n\n"

    msg += f"💡 <b>오늘의 실전 매매 액션 플랜</b>\n{guide}\n\n"

    # [아이디어 1] 직전 종가베팅 보유 종목의 NXT 프리마켓/시간외 실시간 체결 시세 및 개별 대응 가이드
    try:
        from src.track_record import get_latest_closing_record
        from src.recommender import fetch_nxt_over_market_info
        rec = get_latest_closing_record()
        if rec and rec.get('picks'):
            nxt_lines = []
            for p in rec['picks'][:3]:
                nxt = fetch_nxt_over_market_info(p['code'])
                if nxt and nxt.get('price'):
                    r_val = nxt.get('ratio', 0.0)
                    act = "🔥NXT 50% 선제익절 권장" if r_val >= 2.5 else ("🟢09:00 정규장 슈팅 대기" if r_val >= 0 else "⚖️전일종가 지지 확인")
                    nxt_lines.append(f"• <b>{p['name']}</b>: {nxt['session']} <b>{nxt['price']:,}원</b> ({r_val:+.2f}%) → <i>{act}</i>")
            if nxt_lines:
                msg += "⚡ <b>[종가베팅 종목 NXT 실시간 시세 & 시차 대응]</b>\n" + "\n".join(nxt_lines) + "\n\n"
    except Exception as e:
        logger.debug(f"NXT 시세 브리핑 생략: {e}")

    # [STEP 4] 전일 종가베팅 사후 성과 검증 피드백 자동 삽입
    try:
        from src.track_record import evaluate_latest_performance
        track_feedback = evaluate_latest_performance()
        if track_feedback:
            msg += f"{track_feedback}\n"
    except Exception as e:
        logger.warning(f"트랙 레코드 피드백 생성 실패: {e}")

    msg += f"🔗 <b>실시간 대시보드</b>: {DASHBOARD_URL}"
    return msg


# ==========================================================
# 3. [오후 15:10] 정규장 1차 종가베팅 가이드
#    (15:30 KRX 정규장 마감 20분 전 판단)
# ==========================================================
def get_closing_betting_guide():
    fut_price, fut_ratio = fetch_nasdaq_futures()
    kp_close, kp_ratio, kp_for, kp_inst, kp_for_num, kp_inst_num = fetch_kr_market('KOSPI')
    kd_close, kd_ratio, kd_for, kd_inst, kd_for_num, kd_inst_num = fetch_kr_market('KOSDAQ')
    fx_close, fx_ratio, _ = fetch_usdkrw()
    vix_close, vix_ratio = fetch_vix()
    us10y_price, us10y_diff = fetch_us10y()

    score = 50.0
    score += (fut_ratio * 15) * 0.35

    total_major = kp_for_num + kp_inst_num + kd_for_num + kd_inst_num
    score += min(max(total_major / 150, -30), 30) * 0.35

    avg_kr_ratio = (kp_ratio + kd_ratio) / 2
    score += (avg_kr_ratio * 12) * 0.15
    score -= (fx_ratio * 15) * 0.15

    score = min(max(round(score), 0), 100)
    gauge = make_gauge_bar(score)

    if score >= 75:
        core_action = "🟢 주도 섹터 1등주 적극 종가베팅 (비중 60~80%)"
        betting_label = "[정규장 적극 베팅 | 비중 60~80%]"
        guide = (
            "• <b>공략 대상</b>: 당일 거래대금 최상위 & 신고가/눌림목 주도 섹터 1등주\n"
            "• <b>비중</b>: 투자금의 60~80% 수준으로 정규장 종가베팅이 유효합니다.\n"
            "• <b>원칙</b>: 외인/기관 메이저 수급이 장 막판까지 지수를 견고히 받치는 종목 우선 선정."
        )
    elif score >= 55:
        core_action = "🟡 확실한 모멘텀/실적 호재주만 선별 베팅 (비중 30~50%)"
        betting_label = "[선별 베팅 | 비중 30~50%]"
        guide = (
            "• <b>전략</b>: 실적 서프라이즈, 자사주 취득 등 개별 모멘텀이 확실한 종목만 30~50% 비중으로 분할 진입하세요.\n"
            "• <b>TIP</b>: 나머지 비중은 19:40 NXT 야간 마감 전 흐름을 보고 추가 진입 여부를 결정하세요."
        )
    elif score >= 40:
        core_action = "🟠 비중 축소 & 현금 우위 유지 (20% 이하 소액만)"
        betting_label = "[보수적 접근 | 비중 20% 이하]"
        guide = (
            "• <b>전략</b>: 무리하게 베팅하지 마시고 확실한 지지 라인이 확인된 종목만 20% 이하 소액 진입하세요.\n"
            "• <b>원칙</b>: 수급 에너지가 분산되어 오버나잇 리스크가 있으므로 현금을 아끼세요."
        )
    else:
        core_action = "🔴 15:30 정규장 종가베팅 절대 금지 (전량 현금 100%)"
        betting_label = "[정규장 베팅 금지 | 전량 현금 100%]"
        guide = (
            "• <b>전략</b>: 외인/기관 양매도 또는 미 선물 급락세로 하방 압력이 큽니다. 무리한 진입 금지!\n"
            "• <b>원칙</b>: 정규장에서는 현금 100%를 지키고, 장 마감 후 나오는 공시와 19:40 NXT 야간 가이드를 확인하세요."
        )

    def arr(r):
        return '🔺' if r > 0 else ('🔻' if r < 0 else '➖')

    fut_arr = arr(fut_ratio) if fut_price else ''
    fx_desc = '원화 강세' if fx_ratio < 0 else '원화 약세'
    vix_str = f"🌪️ VIX: <b>{vix_close}</b>" if vix_close else ""
    us10y_str = f"📈 美10년물: <b>{us10y_price:.2f}%</b>" if us10y_price else ""

    now_kst = datetime.now(KST)
    ko_wd = ['월', '화', '수', '목', '금', '토', '일'][now_kst.weekday()]
    date_str = f"{now_kst.strftime('%m/%d')}({ko_wd})"
    msg = f"🎯 <b>[15:30 정규장 1차 종가베팅 가이드]</b> ({date_str} 15:10 알림)\n"
    msg += "━━━━━━━━━━━━━━━━━━━━\n"
    msg += f"🎯 <b>핵심 전략</b>: <b>{core_action}</b>\n"
    msg += f"📊 <b>시장 점수</b>: <b>{score}점</b> [{gauge}] | <b>{betting_label}</b>\n"
    msg += "━━━━━━━━━━━━━━━━━━━━\n\n"

    msg += "⚡ <b>정규장 마감 수급 & 팩트 체크</b>\n"
    msg += f"• 🇰🇷 코스피: <b>{kp_close}</b> ({kp_ratio:+.2f}%) | 외인 {kp_for}억, 기관 {kp_inst}억\n"
    msg += f"• 🇰🇷 코스닥: <b>{kd_close}</b> ({kd_ratio:+.2f}%) | 외인 {kd_for}억, 기관 {kd_inst}억\n"
    if fut_price:
        msg += f"• 🇺🇸 NQ선물: <b>{fut_price:,.1f}</b> ({fut_ratio:+.2f}%) {fut_arr} | 💱 환율: <b>{fx_close}원</b> ({fx_desc})\n"
    if vix_str and us10y_str:
        msg += f"• {vix_str} | {us10y_str}\n"

    msg += f"\n💡 <b>정규장 종가베팅 전략</b>\n{guide}\n"

    try:
        from src.recommender import get_recommendations, format_marcap
        rec = get_recommendations()
        closing_picks = rec.get('closing', [])
        if closing_picks:
            msg += "\n🔥 <b>오늘의 AI 종가베팅 주도주 TOP 3 (지지·저항 돌파)</b>\n"
            for idx, s in enumerate(closing_picks[:3], 1):
                chart_url = s.get('chart_url', f"https://m.stock.naver.com/domestic/stock/{s['code']}/total")
                sec = s.get('sector', '주도주')
                cat = s.get('catalyst')
                cat_url = s.get('catalyst_url') or chart_url
                cat_src = s.get('catalyst_source', '')
                sr_status = s.get('sr_status')
                support_p = s.get('support_price')
                next_res = s.get('next_resistance')
                marcap_str = s.get('marcap_str') or (format_marcap(s.get('marcap')) if s.get('marcap') else '')
                marcap_part = f" | 🏢 시총: <b>{marcap_str}</b>" if marcap_str else ""

                msg += f"{idx}. <a href=\"{chart_url}\"><b>{s['name']}</b></a> (<b>{s['change_pct']:+.2f}%</b>) 🏷️ <code>[{sec}]</code>\n"
                msg += f"   ├ 💰 거래대금: <b>{s['amount_eok']:,}억</b>{marcap_part} (종가: {s['price']:,}원)\n"
                if sr_status:
                    msg += f"   ├ 📈 <b>차트분석</b>: {sr_status}\n"
                    if support_p and next_res:
                        msg += f"   ├ 🛡️ <b>지지</b>: {support_p:,}원 | 🚀 <b>저항</b>: {next_res}\n"
                if cat:
                    src_tag = f" ({cat_src})" if cat_src else ""
                    msg += f"   ├ 📰 <b>핵심재료</b>: <a href=\"{cat_url}\"><i>{cat}</i>{src_tag} ↗</a>\n"
                msg += f"   ├ 🎯 <b>목표가</b>: <b>{s['target_1']:,}원</b> (+3%) | 손절: {s['stop_loss']:,}원 (-2%)\n"
                msg += f"   └ 📱 <a href=\"{chart_url}\">네이버 증권 차트/호가 바로보기 ↗</a>\n\n"

        swing_picks = rec.get('swing', [])
        if swing_picks:
            msg += "\n🚀 <b>오늘의 2~5일 스윙 추천주 TOP 3 (20일선 눌림목 반등)</b>\n"
            for idx, s in enumerate(swing_picks[:3], 1):
                chart_url = s.get('chart_url', f"https://m.stock.naver.com/domestic/stock/{s['code']}/total")
                sec = s.get('sector', '우량스윙')
                marcap_str = s.get('marcap_str') or (format_marcap(s.get('marcap')) if s.get('marcap') else '')
                marcap_part = f" | 🏢 시총: <b>{marcap_str}</b>" if marcap_str else ""
                hold_period = s.get('holding_period', '2~5거래일')
                target_2_str = f" | 🚀 <b>2차 목표</b>: <b>{s['target_2']:,}원</b> (+9%)" if s.get('target_2') else ""

                msg += f"{idx}. <a href=\"{chart_url}\"><b>{s['name']}</b></a> (<b>{s['change_pct']:+.2f}%</b>) 🏷️ <code>[{sec}]</code>\n"
                msg += f"   ├ 💰 거래대금: <b>{s['amount_eok']:,}억</b>{marcap_part} (종가: {s['price']:,}원)\n"
                msg += f"   ├ 🎯 <b>1차 목표</b>: <b>{s['target_1']:,}원</b> (+5%){target_2_str}\n"
                msg += f"   ├ 🛡️ <b>손절 기준선</b>: {s['stop_loss']:,}원 (-3%) | ⏳ <b>권장 보유</b>: {hold_period}\n"
                if s.get('reason'):
                    msg += f"   ├ 💡 <b>선정 이유</b>: <i>{s['reason']}</i>\n"
                msg += f"   └ 📱 <a href=\"{chart_url}\">네이버 증권 차트/호가 바로보기 ↗</a>\n\n"
        else:
            msg += "\n🚀 <b>오늘의 2~5일 스윙 추천주</b>: 🛡️ 오늘 시장 조건(20일선 정배열 눌림목 & 양봉 돌파)에 부합하는 알짜 주도주가 없어 <b>신규 매수를 전면 보류(0종목)</b>하고 100% 현금을 보존합니다.\n\n"
    except Exception as e:
        logger.warning(f"종가베팅 추천 종목 조회 실패: {e}")

    msg += f"\n🔗 <b>실시간 대시보드</b>: {DASHBOARD_URL}"
    return msg


# ==========================================================
# 4. [오후 19:40] NXT 20:00 마감 최종 종가베팅 가이드
#    (Nextrade 대체거래소/시간외 20:00 종료 20분 전 최종 오버나잇 판정)
# ==========================================================
def get_evening_betting_guide():
    fut_price, fut_ratio = fetch_nasdaq_futures()
    dax_close, dax_ratio = fetch_naver_index('.GDAXI')
    fx_close, fx_ratio, _ = fetch_usdkrw()
    cnn_score, cnn_rating = fetch_cnn_fear_greed()
    vix_close, vix_ratio = fetch_vix()
    us10y_price, us10y_diff = fetch_us10y()

    score = 50.0
    score += (fut_ratio * 18) * 0.45
    score += (dax_ratio * 12) * 0.20
    score += (cnn_score - 50) * 0.15
    score -= (fx_ratio * 15) * 0.20
    if vix_close:
        try:
            v_val = float(str(vix_close).replace(',', ''))
            if v_val > 22.0:
                score -= min((v_val - 22.0) * 1.5, 15)
        except Exception:
            pass
    score = min(max(round(score), 0), 100)
    gauge = make_gauge_bar(score)

    if score >= 75:
        core_action = "🟢 마감 후 호재 공시주 최종 종가베팅 (비중 60~80%)"
        betting_label = "[NXT 야간 최종 베팅 적극 추천 | 비중 60~80%]"
        guide = (
            "• <b>공략 대상</b>: 오늘 정규장 마감 후 발표된 <b>호재 공시주(어닝 서프라이즈/자사주 취득)</b> 및 정규장 주도 대장주\n"
            "• <b>비중</b>: 총 투자금의 60~80% 수준으로 20:00 장 마감 전 적극적인 종가베팅 매수가 유효합니다.\n"
            "• <b>목표</b>: 내일 아침 08:00 NXT 프리마켓 & 09:00 정규장 시초 갭상승 익절!"
        )
    elif score >= 55:
        core_action = "🟡 어닝서프라이즈/자사주 공시주 선별 베팅 (비중 30~50%)"
        betting_label = "[선별 베팅 | 비중 30~50%]"
        guide = (
            "• <b>공략 대상</b>: 지수 연동 대형주보다는 장 마감 후 확실한 실적 서프라이즈나 자사주 공시가 뜬 개별주 위주로 공략하세요.\n"
            "• <b>비중</b>: 비중 30~50% 이내로 조절하여 안정적으로 분할 진입하세요."
        )
    elif score >= 40:
        core_action = "🟠 야간 변동성 주의, 20% 미만 극소액 또는 현금 유지"
        betting_label = "[보수적 접근 | 비중 20% 이하]"
        guide = (
            "• <b>원칙</b>: 무리하게 오버나잇 비중을 늘리지 마시고, 확신이 드는 종목만 20% 미만으로 가볍게 담고 현금을 우선하세요."
        )
    else:
        core_action = "🔴 20:00 NXT 마감 전 전량 현금화 (오버나잇 금지)"
        betting_label = "[야간 종가베팅 절대 금지 | 전량 현금 100%]"
        guide = (
            "• <b>전략</b>: 오늘 밤 종가베팅 진입 시 내일 아침 시초가 갭하락 맞을 위험이 대단히 높습니다.\n"
            "• <b>원칙</b>: 20:00 NXT 거래 종료 전 전량 현금화하여 리스크 없이 편안하게 마감하세요."
        )

    def arr(r):
        return '🔺' if r > 0 else ('🔻' if r < 0 else '➖')

    fut_arr = arr(fut_ratio) if fut_price else ''
    dax_arr = arr(dax_ratio) if dax_close else ''
    fx_desc = '원화 강세' if fx_ratio < 0 else '원화 약세'
    vix_str = f"🌪️ VIX: <b>{vix_close}</b>" if vix_close else ""
    us10y_str = f"📈 美10년물: <b>{us10y_price:.2f}%</b>" if us10y_price else ""

    now_kst = datetime.now(KST)
    ko_wd = ['월', '화', '수', '목', '금', '토', '일'][now_kst.weekday()]
    date_str = f"{now_kst.strftime('%m/%d')}({ko_wd})"
    msg = f"🎯 <b>[20:00 NXT 야간 최종 종가베팅 가이드]</b> ({date_str} 19:40 알림)\n"
    msg += "━━━━━━━━━━━━━━━━━━━━\n"
    msg += f"🎯 <b>핵심 전략</b>: <b>{core_action}</b>\n"
    msg += f"📊 <b>최종 점수</b>: <b>{score}점</b> [{gauge}] | <b>{betting_label}</b>\n"
    msg += "━━━━━━━━━━━━━━━━━━━━\n\n"

    msg += "⚡ <b>야간 글로벌 마켓 현황</b>\n"
    if fut_price and dax_close:
        msg += f"• 🇺🇸 NQ선물: <b>{fut_price:,.1f}</b> ({fut_ratio:+.2f}%) {fut_arr} | 🇪🇺 유럽(DAX): <b>{dax_close}</b> ({dax_ratio:+.2f}%) {dax_arr}\n"
    elif fut_price:
        msg += f"• 🇺🇸 NQ선물: <b>{fut_price:,.1f}</b> ({fut_ratio:+.2f}%) {fut_arr}\n"
    msg += f"• 💱 야간 환율: <b>{fx_close}원</b> ({fx_desc})\n"
    if vix_str and us10y_str:
        msg += f"• {vix_str} | {us10y_str}\n"
    msg += f"• 🧭 CNN 심리: <b>{cnn_score:.0f}점</b> ({cnn_rating.upper()})\n\n"

    msg += f"💡 <b>20:00 마감 전 최종 종가베팅 전략</b>\n{guide}\n"

    try:
        from src.recommender import get_recommendations, format_marcap
        rec = get_recommendations()
        closing_picks = rec.get('closing', [])
        breakout_picks = rec.get('breakout', [])
        seen_codes = set()
        picks = []
        for s in (closing_picks[:2] + breakout_picks[:2]):
            if s['code'] not in seen_codes:
                seen_codes.add(s['code'])
                picks.append(s)
            if len(picks) >= 3:
                break

        if picks:
            msg += "\n🔥 <b>오늘의 주도 대장주 레이더 (지지·저항 돌파)</b>\n"
            for idx, s in enumerate(picks, 1):
                chart_url = s.get('chart_url', f"https://m.stock.naver.com/domestic/stock/{s['code']}/total")
                sec = s.get('sector', '주도주')
                cat = s.get('catalyst')
                cat_url = s.get('catalyst_url') or chart_url
                cat_src = s.get('catalyst_source', '')
                sr_status = s.get('sr_status')
                support_p = s.get('support_price')
                next_res = s.get('next_resistance')
                marcap_str = s.get('marcap_str') or (format_marcap(s.get('marcap')) if s.get('marcap') else '')
                marcap_part = f" | 🏢 시총: <b>{marcap_str}</b>" if marcap_str else ""

                msg += f"{idx}. <a href=\"{chart_url}\"><b>{s['name']}</b></a> (<b>{s['change_pct']:+.2f}%</b>) 🏷️ <code>[{sec}]</code>\n"
                msg += f"   ├ 💰 거래대금: <b>{s['amount_eok']:,}억</b>{marcap_part} (종가: {s['price']:,}원)\n"
                if sr_status:
                    msg += f"   ├ 📈 <b>차트분석</b>: {sr_status}\n"
                    if support_p and next_res:
                        msg += f"   ├ 🛡️ <b>지지</b>: {support_p:,}원 | 🚀 <b>저항</b>: {next_res}\n"
                if cat:
                    src_tag = f" ({cat_src})" if cat_src else ""
                    msg += f"   ├ 📰 <b>핵심재료</b>: <a href=\"{cat_url}\"><i>{cat}</i>{src_tag} ↗</a>\n"
                msg += f"   ├ 🎯 <b>목표가</b>: <b>{s['target_1']:,}원</b> (+3%) | 손절: {s['stop_loss']:,}원 (-2%)\n"
                msg += f"   └ 📱 <a href=\"{chart_url}\">네이버 증권 차트/호가 바로보기 ↗</a>\n\n"
    except Exception as e:
        logger.warning(f"야간 추천 종목 조회 실패: {e}")

    msg += f"\n🔗 <b>실시간 대시보드</b>: {DASHBOARD_URL}"
    return msg


# ==========================================================
# 통합 디스패처: 시간에 따라 자동 분기
# ==========================================================
# ==========================================================
# 3-1. [오후 13:00] 오후장 개시 시황 & 외인/기관 수급 중간점검
# ==========================================================
def get_midday_market_guide():
    kp_close, kp_ratio, kp_for, kp_inst, kp_for_num, kp_inst_num = fetch_kr_market('KOSPI')
    kd_close, kd_ratio, kd_for, kd_inst, kd_for_num, kd_inst_num = fetch_kr_market('KOSDAQ')
    fut_price, fut_ratio = fetch_nasdaq_futures()
    fx_close, fx_ratio, _ = fetch_usdkrw()
    cnn_score, cnn_rating = fetch_cnn_fear_greed()

    now_kst = datetime.now(KST)
    ko_wd = ['월', '화', '수', '목', '금', '토', '일'][now_kst.weekday()]
    date_str = f"{now_kst.strftime('%m/%d')}({ko_wd})"

    # 1. 실제 국내 지수 등락률(가장 핵심!) 및 수급 반영
    avg_kr_ratio = (kp_ratio + kd_ratio) / 2
    total_major = kp_for_num + kp_inst_num + kd_for_num + kd_inst_num

    score = 50.0
    # 국내 지수 실제 등락 반영 (지수 -5% 시 -30점 직행)
    score += min(max(avg_kr_ratio * 6.0, -35), 35)
    # 외인/기관 메이저 수급 반영
    score += min(max(total_major / 100.0, -25), 25)
    # 미 선물 및 환율 반영
    score += (fut_ratio * 10) * 0.20 - (fx_ratio * 15) * 0.15
    score = min(max(round(score), 0), 100)
    gauge = make_gauge_bar(score)

    def arr(r):
        return '🔺' if r > 0 else ('🔻' if r < 0 else '➖')

    fut_arr = arr(fut_ratio) if fut_price else ''
    fx_desc = '원화 강세' if fx_ratio < 0 else '원화 약세'

    # 2. 실제 지수 상황에 따른 정밀 팩트 판정
    if avg_kr_ratio <= -2.5:
        market_status = f"🔴 전면 급락/투매 장세 (코스피 {kp_ratio:+.2f}%, 코스닥 {kd_ratio:+.2f}%)"
        action_plan = (
            f"• <b>현 시장 팩트</b>: 코스피가 {kp_ratio:+.2f}% 급락 중이며 외인이 {kp_for}억 원을 대규모 투매하고 있습니다.\n"
            f"• <b>실전 전략</b>: 테마주고 대형주고 가릴 것 없이 시장 전반이 초토화된 하락장입니다. 절대 물타기 금지!\n"
            f"• <b>원칙</b>: 신규 매수를 전면 중단하고 100% 현금을 보존하며 장 마감까지 관망하세요."
        )
    elif avg_kr_ratio <= -0.8:
        market_status = f"🟠 지수 약세 조정 장세 (코스피 {kp_ratio:+.2f}%, 코스닥 {kd_ratio:+.2f}%)"
        action_plan = (
            f"• <b>현 시장 팩트</b>: 지수가 하방 압력을 받고 있으며 외인/기관 합산 {total_major:+,}억 매도세가 우세합니다.\n"
            f"• <b>실전 전략</b>: 지수 관련 대형주는 무겁고 지수 방어가 어렵습니다. 무리한 진입 자제.\n"
            f"• <b>원칙</b>: 14:00 사전 레이더에서 거래대금을 지키는 극소수 알짜 종목만 체크하세요."
        )
    elif abs(avg_kr_ratio) < 0.8:
        market_status = f"🟡 박스권 보합/횡보 장세 (코스피 {kp_ratio:+.2f}%, 코스닥 {kd_ratio:+.2f}%)"
        action_plan = (
            f"• <b>현 시장 팩트</b>: 지수가 뚜렷한 방향성 없이 보합권 등락 중입니다. (수급 합산: {total_major:+,}억)\n"
            f"• <b>실전 전략</b>: 지수 변동폭이 좁아 개별 호재를 동반한 종목 위주로 순환매가 돕니다.\n"
            f"• <b>원칙</b>: 뇌동매매를 피하고 14:00~15:10 종가베팅 골든타임까지 호가창을 관망하세요."
        )
    else:
        market_status = f"🟢 지수 견조한 상승 장세 (코스피 {kp_ratio:+.2f}%, 코스닥 {kd_ratio:+.2f}%)"
        action_plan = (
            f"• <b>현 시장 팩트</b>: 지수가 강세를 보이며 외인/기관 메이저 수급이 지수를 견인 중입니다.\n"
            f"• <b>실전 전략</b>: 당일 주도 섹터 1등주의 오후 눌림목 구간을 적극 체크하세요.\n"
            f"• <b>원칙</b>: 14:00 종가베팅 사전 후보 종목 압축에 집중하세요."
        )

    msg = f"☀️ <b>[13:00 오후장 개시 & 수급 중간점검]</b> ({date_str} 13:00 알림)\n"
    msg += "━━━━━━━━━━━━━━━━━━━━\n"
    msg += f"🎯 <b>시장 판정</b>: <b>{market_status}</b>\n"
    msg += f"📊 <b>오후장 점수</b>: <b>{score}점</b> [{gauge}] | <b>메이저 순매수: {total_major:+,}억</b>\n"
    msg += "━━━━━━━━━━━━━━━━━━━━\n\n"

    msg += "⚡ <b>오후장 외인/기관 실시간 수급 현황</b>\n"
    msg += f"• 🇰🇷 코스피: <b>{kp_close}</b> ({kp_ratio:+.2f}%) | 외인 {kp_for}억, 기관 {kp_inst}억\n"
    msg += f"• 🇰🇷 코스닥: <b>{kd_close}</b> ({kd_ratio:+.2f}%) | 외인 {kd_for}억, 기관 {kd_inst}억\n"
    if fut_price:
        msg += f"• 🇺🇸 NQ선물: <b>{fut_price:,.1f}</b> ({fut_ratio:+.2f}%) {fut_arr} | 💱 환율: <b>{fx_close}원</b> ({fx_desc})\n"
    msg += f"• 🧭 CNN 심리: <b>{cnn_score:.0f}점</b> ({cnn_rating.upper()})\n\n"

    msg += f"💡 <b>오후장 실전 대응 가이드</b>\n{action_plan}"

    try:
        from src.market_flow import get_market_flow_data
        flow = get_market_flow_data()
        sectors = flow.get("sectors", [])
        if sectors:
            top_secs = [f"<b>{s['sector_name']}</b> {s['stars']}({s['total_volume_str']})" for s in sectors[:3]]
            msg += f"\n\n💸 <b>실시간 머니플로우 자금 집중 TOP 3</b>\n• " + " | ".join(top_secs)
    except Exception:
        pass

    msg += f"\n\n🔗 <b>실시간 대시보드</b>: {DASHBOARD_URL} (👉 <a href='{DASHBOARD_URL}#tab-flow'>머니플로우 전광판</a>)"
    return msg


# ==========================================================
# 3-2. [오후 14:00] 종가베팅 1시간 전 사전 레이더 & 시장 리스크 점검
# ==========================================================
def get_preclosing_guide():
    kp_close, kp_ratio, kp_for, kp_inst, kp_for_num, kp_inst_num = fetch_kr_market('KOSPI')
    kd_close, kd_ratio, kd_for, kd_inst, kd_for_num, kd_inst_num = fetch_kr_market('KOSDAQ')
    fut_price, fut_ratio = fetch_nasdaq_futures()
    fx_close, fx_ratio, _ = fetch_usdkrw()

    avg_kr_ratio = (kp_ratio + kd_ratio) / 2
    total_major = kp_for_num + kp_inst_num + kd_for_num + kd_inst_num

    score = 50.0
    score += min(max(avg_kr_ratio * 6.0, -35), 35)
    score += min(max(total_major / 100.0, -25), 25)
    score += (fut_ratio * 10) * 0.20 - (fx_ratio * 15) * 0.15
    score = min(max(round(score), 0), 100)
    gauge = make_gauge_bar(score)

    now_kst = datetime.now(KST)
    ko_wd = ['월', '화', '수', '목', '금', '토', '일'][now_kst.weekday()]
    date_str = f"{now_kst.strftime('%m/%d')}({ko_wd})"

    if score >= 70 and avg_kr_ratio > -0.5:
        pre_verdict = "🟢 종가베팅 진입 적합 (15:10 적극 공략 준비)"
        pre_guide = "• <b>예상 비중</b>: 60~80% 적극 진입 가능\n• <b>포인트</b>: 지수와 메이저 수급이 견조하여 15:10 공식 추천 종목 진입 확률이 높습니다."
    elif score >= 45 and avg_kr_ratio > -1.5:
        pre_verdict = "🟡 선별 진입 권장 (확실한 주도주 1종목만 30~50%)"
        pre_guide = "• <b>예상 비중</b>: 30~50% 선별 진입\n• <b>포인트</b>: 지수 변동성이 크므로 거래대금 최상위 & 윗꼬리 짧은 1등주로만 압축 대응하세요."
    else:
        pre_verdict = f"🔴 종가베팅 강력 주의 (지수 {avg_kr_ratio:+.2f}% 급락세 · 전량 현금 권장)"
        pre_guide = (
            f"• <b>현 시장 팩트</b>: 지수가 {avg_kr_ratio:+.2f}% 급락 중이며 외인/기관 메이저 매도세가 극심합니다.\n"
            f"• <b>예상 비중</b>: 0% 전량 현금 권장 (오버나잇 갭하락 위험 극대화)\n"
            f"• <b>포인트</b>: 15:10 종가베팅 최종 판정 점수에서도 차단될 가능성이 매우 높으니 무리한 매수를 절대 금지합니다."
        )

    msg = f"🎯 <b>[14:00 종가베팅 1시간 전 사전 레이더]</b> ({date_str} 14:00 알림)\n"
    msg += "━━━━━━━━━━━━━━━━━━━━\n"
    msg += f"🎯 <b>사전 판정</b>: <b>{pre_verdict}</b>\n"
    msg += f"📊 <b>예비 리스크 점수</b>: <b>{score}점</b> [{gauge}] | <b>15:10 골든타임 1시간 전</b>\n"
    msg += "━━━━━━━━━━━━━━━━━━━━\n\n"

    msg += "⚡ <b>장마감 1시간 전 시장 지표 체크</b>\n"
    msg += f"• 🇰🇷 코스피: <b>{kp_close}</b> ({kp_ratio:+.2f}%) | 외인 {kp_for}억, 기관 {kp_inst}억\n"
    msg += f"• 🇰🇷 코스닥: <b>{kd_close}</b> ({kd_ratio:+.2f}%) | 외인 {kd_for}억, 기관 {kd_inst}억\n"
    if fut_price:
        msg += f"• 🇺🇸 NQ선물: <b>{fut_price:,.1f}</b> ({fut_ratio:+.2f}%) | 💱 환율: <b>{fx_close}원</b>\n"

    msg += f"\n💡 <b>15:10 골든타임 대비 행동 요령</b>\n{pre_guide}\n"

    # 지수 급락(-2.5% 이하) 시에는 위험 종목 매수를 부추기지 않도록 안내
    if avg_kr_ratio <= -2.5:
        msg += "\n⚠️ <b>[리스크 알림]</b> 시장 전면 급락으로 상방 종목이 극히 제한적입니다. 15:10 시스템 차단 여부를 반드시 확인하세요.\n"
    else:
        try:
            from src.recommender import get_recommendations
            rec = get_recommendations()
            closing_picks = rec.get('closing', [])
            if closing_picks:
                msg += "\n🔥 <b>현재 시점 유력 후보 레이더 TOP 3 (15:10 최종 확정)</b>\n"
                for idx, s in enumerate(closing_picks[:3], 1):
                    chart_url = s.get('chart_url', f"https://m.stock.naver.com/domestic/stock/{s['code']}/total")
                    sec = s.get('sector', '주도주')
                    msg += f"{idx}. <a href=\"{chart_url}\"><b>{s['name']}</b></a> (<b>{s['change_pct']:+.2f}%</b>) 🏷️ <code>[{sec}]</code> | 💰 거래대금: <b>{s['amount_eok']:,}억</b>\n"
        except Exception as e:
            logger.warning(f"사전 추천 종목 조회 실패: {e}")

    try:
        from src.market_flow import get_market_flow_data
        flow = get_market_flow_data()
        sectors = flow.get("sectors", [])
        if sectors:
            top_secs = [f"<b>{s['sector_name']}</b> {s['stars']}({s['total_volume_str']})" for s in sectors[:3]]
            msg += f"\n💸 <b>실시간 머니플로우 자금 집중 TOP 3</b>\n• " + " | ".join(top_secs) + "\n"
    except Exception:
        pass

    msg += f"\n🔗 <b>실시간 대시보드 (100% 실시간 갱신)</b>: {DASHBOARD_URL} (👉 <a href='{DASHBOARD_URL}#tab-flow'>머니플로우 전광판</a>)"
    return msg


# ==========================================================
# 3-2. [오후 15:35] 정규장 최종 마감 시황 & 외인/기관 최종 수급 종합 리포트
# ==========================================================
def get_market_close_guide():
    """
    [오후 15:35] 정규장 최종 마감 시황 & 외인/기관 최종 수급 종합 리포트
    15:30 정규장 종료 직후 당일 양대 시장 결과와 종가베팅/스윙 성적을 종합 브리핑합니다.
    """
    kp_close, kp_ratio, kp_for, kp_inst, kp_for_num, kp_inst_num = fetch_kr_market('KOSPI')
    kd_close, kd_ratio, kd_for, kd_inst, kd_for_num, kd_inst_num = fetch_kr_market('KOSDAQ')
    fut_price, fut_ratio = fetch_nasdaq_futures()
    fx_close, fx_ratio, _ = fetch_usdkrw()
    vix_close, vix_ratio = fetch_vix()
    us10y_price, us10y_diff = fetch_us10y()

    def arr(r):
        return '🔺' if r > 0 else ('🔻' if r < 0 else '➖')

    kp_arr = arr(kp_ratio)
    kd_arr = arr(kd_ratio)
    fut_arr = arr(fut_ratio) if fut_price else ''
    fx_desc = '원화 강세' if fx_ratio < 0 else '원화 약세'
    vix_str = f"🌪️ VIX: <b>{vix_close}</b>" if vix_close else ""
    us10y_str = f"📈 美10년물: <b>{us10y_price:.2f}%</b>" if us10y_price else ""

    now_kst = datetime.now(KST)
    ko_wd = ['월', '화', '수', '목', '금', '토', '일'][now_kst.weekday()]
    date_str = f"{now_kst.strftime('%m/%d')}({ko_wd})"

    total_major = kp_for_num + kp_inst_num + kd_for_num + kd_inst_num
    if total_major >= 3000:
        market_summary = "외인·기관의 강력한 쌍끌이 순매수로 양대 시장이 탄탄하게 마감되었습니다."
    elif total_major <= -3000:
        market_summary = "외인·기관의 동반 순매도세로 지수 하방 압력을 받으며 보수적으로 마감되었습니다."
    else:
        market_summary = "외인·기관의 수급 공방 속에 개별 종목 장세로 정규장이 마감되었습니다."

    msg = f"🏁 <b>[15:35 정규장 최종 마감 종합 리포트]</b> ({date_str} 15:35 알림)\n"
    msg += "━━━━━━━━━━━━━━━━━━━━\n"
    msg += f"📢 <b>장 마감 총평</b>: <b>{market_summary}</b>\n"
    msg += "━━━━━━━━━━━━━━━━━━━━\n\n"

    msg += "📊 <b>1. 정규장 최종 마감 지수 & 수급</b>\n"
    msg += f"• 🇰🇷 코스피: <b>{kp_close}</b> ({kp_ratio:+.2f}%) {kp_arr} | 외인 <b>{kp_for}억</b>, 기관 <b>{kp_inst}억</b>\n"
    msg += f"• 🇰🇷 코스닥: <b>{kd_close}</b> ({kd_ratio:+.2f}%) {kd_arr} | 외인 <b>{kd_for}억</b>, 기관 <b>{kd_inst}억</b>\n"
    if fut_price:
        msg += f"• 🇺🇸 NQ선물: <b>{fut_price:,.1f}</b> ({fut_ratio:+.2f}%) {fut_arr} | 💱 마감 환율: <b>{fx_close}원</b> ({fx_desc})\n"
    if vix_str and us10y_str:
        msg += f"• {vix_str} | {us10y_str}\n"

    try:
        from src.recommender import get_recommendations
        rec = get_recommendations()
        closing_picks = rec.get('closing', [])
        swing_picks = rec.get('swing', [])

        if closing_picks:
            msg += "\n🎯 <b>2. 오늘 AI 종가베팅 주도주 최종 종가</b>\n"
            for idx, s in enumerate(closing_picks[:2], 1):
                chart_url = s.get('chart_url', f"https://m.stock.naver.com/domestic/stock/{s['code']}/total")
                msg += f"• {idx}등: <a href=\"{chart_url}\"><b>{s['name']}</b></a> ({s.get('change_pct', 0.0):+.2f}%) — 마감가 <b>{s.get('price', 0):,}원</b>\n"
                msg += f"  ↳ 1차 익절목표: {s.get('target_1', 0):,}원 (+2~3%) | 손절선: {s.get('stop_loss', 0):,}원 (-2%)\n"

        if swing_picks:
            msg += "\n🚀 <b>3. 2~5일 스윙 주도주 최종 종가</b>\n"
            for idx, s in enumerate(swing_picks[:2], 1):
                chart_url = s.get('chart_url', f"https://m.stock.naver.com/domestic/stock/{s['code']}/total")
                msg += f"• <a href=\"{chart_url}\"><b>{s['name']}</b></a> ({s.get('change_pct', 0.0):+.2f}%) — 마감가 <b>{s.get('price', 0):,}원</b> (거래대금 {s.get('amount_eok', 0):,}억)\n"
    except Exception as e:
        logger.warning(f"마감 추천 종목 로드 실패: {e}")

    try:
        from src.market_flow import get_market_flow_data
        flow = get_market_flow_data()
        sectors = flow.get("sectors", [])
        if sectors:
            top_secs = [f"<b>{s['sector_name']}</b> {s['stars']}({s['total_volume_str']})" for s in sectors[:3]]
            msg += f"\n💸 <b>정규장 머니플로우 자금 집중 TOP 3</b>\n• " + " | ".join(top_secs) + "\n"
    except Exception:
        pass

    msg += "\n🌙 <b>4. Nextrade 야간마켓 & 향후 일정</b>\n"
    msg += "• <b>넥스트레이드(Nextrade) 애프터마켓</b>: 15:30 ~ 20:00 거래 진행 중\n"
    msg += "• <b>19:40</b>: 20:00 야간마켓 종료 20분 전 [최종 오버나잇 판정 가이드] 발송 예정\n"
    msg += f"\n🔗 <b>실시간 대시보드</b>: {DASHBOARD_URL}"
    return msg


def get_market_score_message(mode=None):
    """
    지정된 mode 또는 현재 KST 시간에 맞춰 가이드 반환
    """
    if not mode or mode == 'auto':
        now_kst = datetime.now(KST)
        hour = now_kst.hour
        minute = now_kst.minute

        if (hour == 6) or (hour == 7) or (hour == 8 and minute < 15):
            mode = 'morning_740'
        elif 8 <= hour < 11:
            mode = 'morning_840'
        elif hour == 13:
            mode = 'midday_1300'
        elif hour == 14 and minute < 45:
            mode = 'preclosing_1400'
        elif (hour == 14 and minute >= 45) or (hour == 15 and minute < 28):
            mode = 'closing'
        elif (hour == 15 and minute >= 28) or (16 <= hour < 18):
            mode = 'close_1535'
        else:
            mode = 'night'

    if mode in ('morning_740', 'morning'):
        return get_morning_sell_guide(time_label="07:40", is_nxt=True)
    elif mode == 'morning_840':
        return get_morning_sell_guide(time_label="08:40", is_nxt=False)
    elif mode == 'midday_1300':
        return get_midday_market_guide()
    elif mode == 'preclosing_1400':
        return get_preclosing_guide()
    elif mode == 'closing':
        return get_closing_betting_guide()
    elif mode in ('close_1535', 'market_close'):
        return get_market_close_guide()
    else:
        return get_evening_betting_guide()
