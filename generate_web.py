"""
비니stock 웹 대시보드 (index.html) 정적 생성 스크립트
실시간 시황 데이터, E-mini 나스닥 선물, 외인/기관 수급, 최근 핵심 공시를 수집하여
초프리미엄 반응형 다크모드 대시보드(HTML/CSS)를 생성합니다.
"""
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Windows 콘솔 출력 인코딩 안전화
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

sys.path.insert(0, str(Path(__file__).parent))

from src.market_score import (
    fetch_nasdaq_futures,
    fetch_naver_index,
    fetch_usdkrw,
    fetch_cnn_fear_greed,
    fetch_kr_market,
    fetch_vix,
    fetch_us10y,
    get_market_score_message,
)
from src import recommender

KST = timezone(timedelta(hours=9))


def generate_html():
    now_kst = datetime.now(KST)
    now_str = now_kst.strftime("%Y-%m-%d %H:%M:%S KST")
    ko_weekdays = ['월', '화', '수', '목', '금', '토', '일']
    guide_date_badge = f"{now_kst.strftime('%Y-%m-%d')} ({ko_weekdays[now_kst.weekday()]}) 최신"
    guide_date_label = f"{now_kst.strftime('%Y년 %m월 %d일')} ({ko_weekdays[now_kst.weekday()]})"

    # 1. 시황 지표 수집
    fut_price, fut_ratio = fetch_nasdaq_futures()
    nas_close, nas_ratio = fetch_naver_index('.IXIC')
    sox_close, sox_ratio = fetch_naver_index('.SOX')
    dax_close, dax_ratio = fetch_naver_index('.GDAXI')
    fx_close, fx_ratio, fx_diff = fetch_usdkrw()
    cnn_score, cnn_rating = fetch_cnn_fear_greed()
    vix_close, vix_ratio = fetch_vix()
    us10y_price, us10y_diff = fetch_us10y()

    kp_close, kp_ratio, kp_for, kp_inst, kp_for_num, kp_inst_num = fetch_kr_market('KOSPI')
    kd_close, kd_ratio, kd_for, kd_inst, kd_for_num, kd_inst_num = fetch_kr_market('KOSDAQ')

    # 2. 4대 가이드 메시지 수집
    guide_0740 = get_market_score_message('morning_740')
    guide_0840 = get_market_score_message('morning_840')
    guide_1510 = get_market_score_message('closing')
    guide_1940 = get_market_score_message('night')

    # Python 3.12 미만 호환: f-string 표현식 내부 백슬래시 금지 → 미리 이스케이프
    bt, bt_esc = '`', '\\`'
    g0740_js = guide_0740.replace(bt, bt_esc)
    g0840_js = guide_0840.replace(bt, bt_esc)
    g1510_js = guide_1510.replace(bt, bt_esc)
    g1940_js = guide_1940.replace(bt, bt_esc)

    # 2-1. AI 실전 추천 종목 수집 (종가베팅 & 2~5일 스윙)
    # 2-0. 실시간 복합 AI 리스크 사전 계산
    try:
        from src.risk_score import compute_risk_score, get_risk_assessment
        vix_val_init = float(str(vix_close).replace(',', '')) if vix_close else 20.0
        pre_risk_ctx = {
            'fut_ratio': fut_ratio if fut_ratio is not None else 0.0,
            'sox_ratio': sox_ratio if sox_ratio is not None else 0.0,
            'kp_ratio': kp_ratio if kp_ratio is not None else 0.0,
            'kd_ratio': kd_ratio if kd_ratio is not None else 0.0,
            'kp_for_num': kp_for_num if kp_for_num is not None else 0,
            'kp_inst_num': kp_inst_num if kp_inst_num is not None else 0,
            'kd_for_num': kd_for_num if kd_for_num is not None else 0,
            'kd_inst_num': kd_inst_num if kd_inst_num is not None else 0,
            'fx_ratio': fx_ratio if fx_ratio is not None else 0.0,
            'fx_close': fx_close if fx_close else 1350.0,
            'cnn_score': cnn_score if cnn_score is not None else 50.0,
            'vix': vix_val_init,
            'us10y': us10y_diff if us10y_diff is not None else 0.0,
        }
        pre_ai_risk = compute_risk_score(pre_risk_ctx)
    except Exception:
        pre_ai_risk = 50

    market_ctx = {
        'fut_ratio': fut_ratio,
        'kp_for_num': kp_for_num,
        'kd_for_num': kd_for_num,
        'cnn_score': cnn_score,
        'vix_close': vix_close,
        'ai_risk_score': pre_ai_risk,
    }
    try:
        rec_data = recommender.get_recommendations(market_context=market_ctx)
        rec_regime = rec_data.get('regime', {})
        closing_picks = rec_data.get('closing', [])
        swing_picks = rec_data.get('swing', [])
        breakout_picks = rec_data.get('breakout', [])
        pullback_picks = rec_data.get('pullback', [])
        condition_picks = rec_data.get('condition', [])
        condition_meta = rec_data.get('condition_meta', {})
        hot_sectors = rec_data.get('hot_sectors', [])
    except Exception as e:
        print(f"추천 종목 수집 실패: {e}")
        fallback = recommender.get_fallback_recommendations()
        rec_regime = fallback.get('regime', {})
        closing_picks = fallback['closing']
        swing_picks = fallback['swing']
        breakout_picks = fallback.get('breakout', [])
        pullback_picks = fallback.get('pullback', [])
        condition_picks = fallback.get('condition', [])
        condition_meta = fallback.get('condition_meta', {})
        hot_sectors = fallback.get('hot_sectors', [])

    hm_kst = now_kst.hour * 100 + now_kst.minute
    is_closing_window = (now_kst.weekday() < 5) and (1500 <= hm_kst <= 1545)

        # 2-X. 오늘의 시장 흐름 (머니플로우) 데이터 로드 & HTML 렌더링
    try:
        from src.market_flow import get_market_flow_data, render_market_flow_html
        flow_data = get_market_flow_data()
        market_flow_html = render_market_flow_html(flow_data)
    except Exception as e:
        print(f"시장 흐름 데이터 로드 실패: {e}")
        market_flow_html = '<div class="empty-card">시장 흐름 데이터를 불러오지 못했습니다.</div>'

    # 2-2. AI 실시간 복합 리스크 스코어 계산 (0~100)
    breadth_val = rec_data.get('breadth_pct', 50.0) if isinstance(rec_data, dict) else 50.0
    kp_pb = 0.0
    kd_pb = 0.0
    try:
        from src.risk_score import compute_risk_score, get_risk_assessment, fetch_index_intraday_pullback
        vix_val = float(str(vix_close).replace(',', '')) if vix_close else 20.0
        kp_pb = fetch_index_intraday_pullback("KOSPI")
        kd_pb = fetch_index_intraday_pullback("KOSDAQ")
        risk_ctx = {
            'fut_ratio': fut_ratio if fut_ratio is not None else 0.0,
            'sox_ratio': sox_ratio if sox_ratio is not None else 0.0,
            'kp_ratio': kp_ratio if kp_ratio is not None else 0.0,
            'kd_ratio': kd_ratio if kd_ratio is not None else 0.0,
            'kp_for_num': kp_for_num if kp_for_num is not None else 0,
            'kp_inst_num': kp_inst_num if kp_inst_num is not None else 0,
            'kd_for_num': kd_for_num if kd_for_num is not None else 0,
            'kd_inst_num': kd_inst_num if kd_inst_num is not None else 0,
            'kp_pullback_pctp': kp_pb,
            'kd_pullback_pctp': kd_pb,
            'breadth_pct': breadth_val,
            'fx_ratio': fx_ratio if fx_ratio is not None else 0.0,
            'fx_close': fx_close if fx_close else 1350.0,
            'cnn_score': cnn_score if cnn_score is not None else 50.0,
            'vix': vix_val,
            'us10y': us10y_diff if us10y_diff is not None else 0.0,
        }
        ai_risk_score = compute_risk_score(risk_ctx)
        assessment = get_risk_assessment(ai_risk_score)
        risk_grade = assessment['grade']
        risk_color = assessment['color']
        risk_badge_class = assessment['badge_class']
        risk_desc = f"{assessment['desc']} <span style='color:#93c5fd; font-weight:600;'>[v2.0 황금비율: 국내체력 53% : 글로벌 47% | 상승종목 {breadth_val:.1f}% · 지수윗꼬리 {kp_pb:.2f}%p]</span>"
    except Exception as e:
        print(f"리스크 스코어 계산 실패: {e}")
        ai_risk_score = 50
        risk_grade = "주의 (중위험)"
        risk_color = "#f59e0b"
        risk_badge_class = "risk-caution"
        risk_desc = "단기 변동성 주의: 분할 매수 및 익절 원칙 준수"

    try:
        from src.track_record import get_latest_closing_record, render_monthly_history_html, evaluate_latest_performance
        for _ in range(5):
            if not evaluate_latest_performance():
                break
        latest_record = get_latest_closing_record()
    except Exception as e:
        latest_record = None

    try:
        from src.track_record import get_self_tuning_insights
        tuning_info = get_self_tuning_insights()
    except Exception:
        tuning_info = {'win_rate': 75.0, 'rr_ratio': 2.15, 'half_kelly_pct': 60.0, 'top_sectors_summary': '반도체, 전력/원전'}

    kelly_win_rate = tuning_info.get('win_rate', 75.0)
    kelly_rr = tuning_info.get('rr_ratio', 2.15)
    kelly_base_pct = tuning_info.get('half_kelly_pct', 60.0)
    if ai_risk_score > 65:
        recommended_invest_pct = 0
    else:
        recommended_invest_pct = int(round(max(25.0, min(72.0, kelly_base_pct * (1.0 - (ai_risk_score / 115.0))))))

    # 칼만 필터(Kalman Filter) 기반 최근 승률 적응형 켈리 자기보정 적용
    try:
        from src.kalman_kelly import calibrate_kelly_with_kalman
        kalman_res = calibrate_kelly_with_kalman(base_invest_pct=recommended_invest_pct, risk_score=ai_risk_score)
        kalman_win_rate = kalman_res['filtered_win_rate']
        kalman_rr = kalman_res['filtered_rr_ratio']
        kalman_mom = kalman_res['momentum_label']
        if ai_risk_score <= 65 and kalman_res.get('calibrated_pct', 0) > 0:
            recommended_invest_pct = int(round(kalman_res['calibrated_pct']))
        elif ai_risk_score > 65:
            recommended_invest_pct = 0
    except Exception as e:
        kalman_res = None
        kalman_win_rate = kelly_win_rate
        kalman_rr = kelly_rr
        kalman_mom = "⚖️ 정상 중립"

    # 종가베팅(15:10)은 익일 09:00~09:20 시초가 대응 전략이므로:
    # - 15:00~15:45 정규장 마감 구간: 당일 실시간 선별 종목 표시
    # - 이전 거래일 종목: 익일 시초가 검증 완료(closing_evaluated) 또는 09:25 이후 장중에는 메인 탭 초기화 (성과 탭에만 보존)
    today_str_kst = now_kst.strftime('%Y-%m-%d')
    if not is_closing_window and latest_record and latest_record.get('picks'):
        closing_ref_date = latest_record['date']
        closing_evaluated = bool(latest_record.get('evaluated', False))
        is_past_closing_pick = (closing_ref_date < today_str_kst)
        if is_past_closing_pick and (closing_evaluated or hm_kst >= 925 or now_kst.weekday() >= 5):
            closing_picks = []
        else:
            closing_picks = latest_record['picks']
    else:
        closing_ref_date = today_str_kst
        closing_evaluated = False

    if is_closing_window:
        short_ref_date = closing_ref_date[5:] if len(str(closing_ref_date)) >= 10 else closing_ref_date
        closing_tab_title = "⚡ 오늘 15:10 종가베팅"
        closing_tab_pill = f"{short_ref_date} 골든타임 · 익일 +3~5%"
        closing_banner_html = f"<b>🎯 오늘({closing_ref_date}) 15:10 종가베팅 추천 종목</b>: 오후 15:10~15:30 매수 체결 → 익일 아침 09:00~09:20 시초가 갭상승 시 전량 분할 익절 (+3%~+5%)"
    else:
        short_ref_date = closing_ref_date[5:] if len(str(closing_ref_date)) >= 10 else closing_ref_date
        if not closing_picks and closing_ref_date < today_str_kst:
            closing_tab_title = "⚡ 15:20 종가베팅"
            closing_tab_pill = "오늘 15:10 선별 대기"
            closing_banner_html = (
                f"<b>🎯 직전({closing_ref_date}) 종가베팅 시초가 검증 완료</b>: 장중 메인 추천 목록 초기화 완료 · "
                "지난 결과는 <b>[📊 1개월 종가베팅 성과]</b> 탭에 보존됩니다 (오늘 15:10 정규장 마감 시 새 종목 자동 선별)"
            )
        elif closing_evaluated:
            closing_tab_title = "⚡ 15:20 종가베팅"
            closing_tab_pill = f"{short_ref_date} 검증완료 · 익일 +3~5%"
            closing_banner_html = f"<b>🎯 직전({closing_ref_date}) 종가베팅 시초가 검증 완료</b>: 익일 시초가 매도 완료 구간 (오늘 15:10 정규장 마감 시 새로운 종목으로 자동 교체됩니다)"
        else:
            closing_tab_title = "⚡ 15:20 종가베팅"
            closing_tab_pill = f"{short_ref_date} 매수대응 · 익일 +3~5%"
            closing_banner_html = f"<b>🎯 직전({closing_ref_date}) 종가베팅 공식 추천 종목</b>: 오늘 아침 09:00~09:20 시초가 갭상승 시 전량 분할 익절 (+3%~+5%) 대응 구간 (오늘 15:10에 새 종목 선별)"

    try:
        history_tab_html = render_monthly_history_html()
    except Exception as e:
        print(f"히스토리 탭 생성 실패: {e}")
        history_tab_html = "<div class='empty-card'>기록을 불러오는 중입니다..</div>"

    try:
        from src.swing_track_record import render_monthly_swing_history_html, evaluate_swing_performance
        evaluate_swing_performance()
        swing_history_tab_html = render_monthly_swing_history_html()
    except Exception as e:
        print(f"스윙 히스토리 탭 생성 실패: {e}")
        swing_history_tab_html = "<div class='empty-card'>스윙 기록을 불러오는 중입니다..</div>"

    # 스윙 What-If 시뮬레이터 카드 생성
    try:
        from src.swing_simulator import render_swing_simulator_card
        swing_sim_card_html = render_swing_simulator_card(swing_picks)
    except Exception as e:
        print(f"스윙 시뮬레이터 생성 실패: {e}")
        swing_sim_card_html = ""

    def render_rec_card(pick, card_theme):
        name = pick.get('name', '종목')
        code = pick.get('code', '')
        market = pick.get('market', 'KRX')
        score = pick.get('score', 92)
        price = pick.get('price', pick.get('close_price', 0))
        change_val = pick.get('change_pct', 0)
        amount_eok = pick.get('amount_eok', 0)
        marcap_str = pick.get('marcap_str', '')
        marcap_val = pick.get('marcap', 0)
        turnover_pct = pick.get('turnover_pct')
        if not turnover_pct and amount_eok and marcap_val and marcap_val > 0:
            turnover_pct = round((float(amount_eok) / (float(marcap_val) / 1e8)) * 100, 2)
        turnover_str = f" · 회전율 {turnover_pct:.2f}%" if turnover_pct else ""
        marcap_badge = f'<span class="rec-marcap-badge">시총 {marcap_str}{turnover_str}</span>' if marcap_str else ''
        amount_str = f" (거래대금 {amount_eok:,}억{turnover_str})" if amount_eok else ""

        t1 = pick.get('target_1') or (int(round(price * 1.03)) if price else 0)
        t1_pct = pick.get('target_1_pct', '+3.0%')
        t2 = pick.get('target_2') or (int(round(price * 1.05)) if price else 0)
        t2_pct = pick.get('target_2_pct', '+5.0%')
        sl = pick.get('stop_loss') or (int(round(price * 0.98)) if price else 0)
        sl_pct = pick.get('stop_loss_pct', '-2.0%')
        t3 = pick.get('target_3')
        t3_pct = pick.get('target_3_pct', '+9.0%')
        t3_col = f'''
                <div class="target-col col-t3">
                    <div class="t-label">3차 목표가 ({t3_pct})</div>
                    <div class="t-val">{t3:,}원</div>
                </div>''' if t3 else ''
        target_box_cls = 'rec-target-box four-col' if t3 else 'rec-target-box'
        rec_date_html = pick.get('rec_date_html', '')

        reason = pick.get('reason', '오후 15:10 메이저 수급 집중 및 익일 갭상승 확률 극대화 종목')
        holding_period = pick.get('holding_period', '당일 15:10~15:30 매수 → 익일 09:00~09:20 전량 분할 매도')

        tags_html = "".join([f'<span class="rec-tag">{t}</span>' for t in pick.get('tags', ['종가베팅', '주도주'])])
        change_class = 'up' if change_val > 0 else ('down' if change_val < 0 else '')
        sign = '+' if change_val > 0 else ''
        sec = pick.get('sector')
        sec_badge = f'<span class="rec-sector-badge">[{sec}]</span>' if sec else ''
        cat = pick.get('catalyst')
        cat_url = pick.get('catalyst_url', f"https://m.stock.naver.com/domestic/stock/{code}/news")
        cat_src = pick.get('catalyst_source', '')
        cat_body = pick.get('catalyst_body', '')
        cat_box = ''
        if cat:
            src_tag = f'<span class="cat-source">{cat_src}</span>' if cat_src else ''
            body_html = f'<div class="cat-body-snippet">{cat_body}...</div>' if cat_body else ''
            cat_box = f'''
            <div class="rec-cat-card">
                <div class="cat-card-header">
                    <div class="cat-badge-group">
                        <span class="cat-label">📰 핵심재료</span>
                        {src_tag}
                    </div>
                    <a href="{cat_url}" target="_blank" rel="noopener noreferrer" class="cat-link-btn">
                        기사 원문 확인 ↗
                    </a>
                </div>
                <div class="cat-headline">
                    <a href="{cat_url}" target="_blank" rel="noopener noreferrer">
                        {cat}
                    </a>
                </div>
                {body_html}
            </div>
            '''
        chart_url = pick.get('chart_url', f"https://m.stock.naver.com/domestic/stock/{code}/total")

        sr_status = pick.get('sr_status')
        support_p = pick.get('support_price', sl)
        next_res = pick.get('next_resistance', f"{t1:,}원 (+3% 목표)")
        sr_box = ''
        if sr_status:
            sr_box = f"""
            <div class="rec-sr-box">
                <div class="sr-status-line">📊 <b>차트 분석</b>: <span class="sr-badge">{sr_status}</span></div>
                <div class="sr-price-line">
                    <span class="sr-pill pill-green">🛡️ 1차 지지선: <b>{support_p:,}원</b></span>
                    <span class="sr-pill pill-gold">🚀 상단 저항선: <b>{next_res}</b></span>
                </div>
            </div>
            """

        # [아이디어 1, 2, 3, 6, 9] RVOL · 회전율 · VWAP · NXT 시세 · 켈리 시드 연동 주문량 박스
        rvol_val = pick.get('rvol')
        turn_val = pick.get('turnover_pct')
        vwap_diff = pick.get('vwap_diff_pct')
        peak_t = pick.get('peak_time')
        nxt_info = pick.get('nxt_info')

        micro_pills = []
        if rvol_val:
            micro_pills.append(f'<span class="sr-pill pill-gold">🔥 상대거래량 RVOL <b>{rvol_val:.1f}배</b></span>')
        if turn_val:
            micro_pills.append(f'<span class="sr-pill pill-green">💫 시총회전율 <b>{turn_val:.1f}%</b></span>')
        if vwap_diff is not None:
            pk_str = f" · 고점 {peak_t}" if peak_t else ""
            micro_pills.append(f'<span class="sr-pill pill-green">📈 VWAP <b>{vwap_diff:+.1f}%</b>{pk_str}</span>')
        if nxt_info and nxt_info.get('price'):
            n_r = nxt_info.get('ratio', 0.0)
            micro_pills.append(f'<span class="sr-pill pill-gold">🌙 {nxt_info["session"]} <b>{nxt_info["price"]:,}원</b> ({n_r:+.2f}%)</span>')

        micro_pills_html = f'<div class="sr-price-line" style="margin-top:6px;">{"".join(micro_pills)}</div>' if micro_pills else ''
        kelly_order_box = f'<div class="rec-kelly-order-box" data-price="{price}" style="margin-top:8px; padding:7px 10px; background:rgba(59,130,246,0.1); border:1px solid rgba(59,130,246,0.3); border-radius:7px; font-size:0.77rem; color:#93c5fd;">💰 <b>내 시드 맞춤 권장 매수량</b>: 계산 중...</div>' if price else ''
        micro_box = micro_pills_html + kelly_order_box

        eval_box = ""
        open_p = pick.get('open_price')
        gap_p = pick.get('gap_pct')
        if open_p is not None and gap_p is not None:
            gap_sign = '+' if gap_p > 0 else ''
            badge_text = '🎯 익절 성공' if pick.get('is_success') else ('✨ 보합' if gap_p >= 0 else '🔻 손절/이탈')
            badge_color = '#ef4444' if gap_p > 0 else '#3b82f6'
            eval_box = f"""
            <div style="margin: 8px 0; padding: 6px 10px; background: rgba(255,255,255,0.06); border-radius: 6px; font-size: 0.85rem; border-left: 3px solid {badge_color}; display: flex; justify-content: space-between; align-items: center;">
                <span>📊 <b>시초가 성과</b>: 종가 {price:,}원 → 시초가 <b>{open_p:,}원</b></span>
                <span style="font-weight: bold; color: {badge_color};">{gap_sign}{gap_p:.2f}% {badge_text}</span>
            </div>
            """

        return f"""
        <div class="rec-card {card_theme}" data-marcap="{int(pick.get('marcap', 0))}">
            <div class="rec-card-top">
                <div class="rec-stock-title">
                    <a href="{chart_url}" target="_blank" rel="noopener noreferrer">
                        {name} <span class="rec-code">{code}</span>
                    </a>
                    {sec_badge}
                    <span class="rec-market-badge">{market}</span>
                    {marcap_badge}
                </div>
                <div class="rec-score-badge">⭐ AI 적중도 {score}점</div>
            </div>
            {rec_date_html}
            {eval_box}

            <div class="rec-price-row">
                <div>
                    <span class="rec-label">추천 매수가</span>
                    <span class="rec-price">{price:,}원</span>
                </div>
                <div class="rec-change-box {change_class}">
                    {sign}{change_val:.2f}%{amount_str}
                </div>
            </div>

            <div class="{target_box_cls}">
                <div class="target-col col-t1">
                    <div class="t-label">1차 목표가 ({t1_pct})</div>
                    <div class="t-val">{t1:,}원</div>
                </div>
                <div class="target-col col-t2">
                    <div class="t-label">2차 목표가 ({t2_pct})</div>
                    <div class="t-val">{t2:,}원</div>
                </div>{t3_col}
                <div class="target-col col-sl">
                    <div class="t-label">손절 기준 ({sl_pct})</div>
                    <div class="t-val">{sl:,}원</div>
                </div>
            </div>

            <div class="rec-desc-box">
                <div class="rec-desc-title">💡 AI 포착 근거:</div>
                <div class="rec-desc-text">{reason}</div>
                {sr_box}
                {micro_box}
                {cat_box}
                <div class="rec-period-tag">⏱️ 매매 타이밍: {holding_period}</div>
            </div>

            <div class="rec-bottom-action">
                <a href="{chart_url}" target="_blank" rel="noopener noreferrer" class="rec-chart-link">
                    📱 실시간 호가 및 일봉 차트 확인 ↗
                </a>
            </div>

            <div class="rec-tags-row">
                {tags_html}
            </div>
        </div>
        """

    if closing_picks:
        closing_cards_html = "".join([render_rec_card(p, "theme-closing") for p in closing_picks])
    elif not is_closing_window and closing_ref_date < today_str_kst:
        closing_cards_html = (
            "<div class='empty-card'>"
            f"⏳ 직전(<b>{closing_ref_date}</b>) 종가베팅 시초가 대응·검증이 완료되어 추천 카드를 초기화했습니다.<br>"
            "직전 매매 내역은 상단 <b>[📊 1개월 종가베팅 성과]</b> 탭에서 확인할 수 있으며, 오늘 <b>15:10</b> 정규장 마감 시 새 종목으로 자동 갱신됩니다."
            "</div>"
        )
    else:
        closing_cards_html = (
            "<div class='empty-card'>"
            f"🛡️ 오늘(<b>{closing_ref_date}</b>) 엄격한 S급 기준(시총·거래대금·회전율·상단매물·AI 80점 이상)을 모두 통과한 종가베팅 종목이 없어 무포지션 현금 보존을 권장합니다."
            "</div>"
        )
    # 시장 환경 연동 스윙 레짐 요약
    active_swing_stg = rec_data.get('swing_regime') or (swing_picks[0] if swing_picks else {})
    swing_regime_label = active_swing_stg.get('mode_label', '🛡️ 방어형 3분할 (하락/혼조장)')
    swing_regime_summary = active_swing_stg.get('mode_desc', '1차 +3%에서 1/3 조기 익절 후 손절선을 본절로 상향')

    # 스윙 추천일 배지: 스캔 시각 + (이전에도 추천된 종목이면) 최초 추천일 D+n
    ko_wd_list = ['월', '화', '수', '목', '금', '토', '일']
    hm_now = now_kst.hour * 100 + now_kst.minute
    if now_kst.weekday() >= 5 or hm_now < 900:
        swing_basis = '직전 거래일 종가 기준'
    elif hm_now <= 1530:
        swing_basis = '장중 실시간 현재가 기준'
    else:
        swing_basis = '당일 종가 기준'
    swing_scan_label = f"{now_kst.strftime('%Y-%m-%d')}({ko_wd_list[now_kst.weekday()]}) {now_kst.strftime('%H:%M')}"
    first_rec_map = {}
    try:
        from src.swing_track_record import load_swing_history
        for h in load_swing_history().get('history', []):
            for hp in h.get('picks', []):
                c = hp.get('code')
                if c and (c not in first_rec_map or h['date'] < first_rec_map[c]['date']) and not hp.get('completed'):
                    first_rec_map[c] = {'date': h['date'], 'entry': hp.get('entry_price', 0), 'status': hp.get('status', '')}
    except Exception as e:
        print(f"스윙 최초 추천일 조회 실패: {e}")
    for sp in swing_picks:
        fr = first_rec_map.get(sp.get('code'))
        prev_html = ''
        if fr and fr['date'] < now_kst.strftime('%Y-%m-%d'):
            prev_html = f" · 🔁 <b>최초 추천 {fr['date']}</b> (진입가 {fr['entry']:,}원 · {fr['status']})"
        m_lbl = sp.get('swing_mode_label', '🛡️ 시장환경 연동')
        sp['rec_date_html'] = (
            f'<div class="rec-date-badge">📅 추천일 <b>{swing_scan_label}</b> 스캔 · {swing_basis} <span style="margin-left:6px; background:rgba(255,255,255,0.12); padding:1px 6px; border-radius:4px; font-weight:700;">{m_lbl}</span>{prev_html}</div>'
        )
    swing_cards_html = "".join([render_rec_card(p, "theme-swing") for p in swing_picks])
    breakout_cards_html = "".join([render_rec_card(p, "theme-breakout") for p in breakout_picks])
    pullback_cards_html = "".join([render_rec_card(p, "theme-swing") for p in pullback_picks]) if pullback_picks else "<div class='empty-card'>현재 과거 기준봉의 5일선·중심선 눌림목 구간에 진입한 종목이 없습니다.</div>"
    cond_cnt = len(condition_picks)
    cond_is_hts = bool(condition_meta.get('is_live_hts'))
    cond_src_badge = "🟢 키움 HTS 실시간 연동" if cond_is_hts else "🔵 클라우드 자체 조건 스캔"
    cond_updated_at = condition_meta.get('updated_at') or now_str
    cond_tab_pill = f"{cond_cnt}종목 포착 · AI 채점" if cond_cnt > 0 else "포착 대기"
    for cp in condition_picks:
        cp['rec_date_html'] = f'<div class="rec-date-badge">🎯 조건식 <b>{condition_meta.get("cond_name", "60일이상추가 1000억")}</b> ({cond_src_badge}) · <b>{cond_updated_at}</b> 기준</div>'
    condition_cards_html = "".join([render_rec_card(p, "theme-condition") for p in condition_picks]) if condition_picks else "<div class='empty-card'>현재 조건검색식('60일이상추가 1000억')에 포착된 종목이 없습니다.</div>"

    hot_sectors_items = []
    for idx_s, hs in enumerate(hot_sectors[:3], 1):
        rank_medal = "🥇 1위" if idx_s == 1 else ("🥈 2위" if idx_s == 2 else "🥉 3위")
        hot_sectors_items.append(f"""
        <div style="flex:1; min-width:220px; background:rgba(255,255,255,0.03); border:1px solid rgba(245,158,11,0.3); border-radius:10px; padding:10px 14px; display:flex; flex-direction:column; gap:4px;">
            <div style="display:flex; justify-content:space-between; align-items:center;">
                <span style="font-weight:800; color:#fbbf24; font-size:0.9rem;">{rank_medal} [{hs.get('sector', '주도주')}]</span>
                <span style="font-size:0.75rem; background:rgba(239,68,68,0.18); color:#f87171; padding:2px 7px; border-radius:999px; font-weight:700;">평균 +{hs.get('avg_chg', 0):.1f}% ({hs.get('count', 1)}종목 폭발)</span>
            </div>
            <div style="font-size:0.78rem; color:#d1d5db;">
                💰 섹터 거래대금 <b>{hs.get('total_amount_eok', 0):,}억</b> | 👑 대장주: <b>{hs.get('leader_name', '-')}</b> (+{hs.get('leader_chg', 0):.1f}%)
            </div>
        </div>
        """)
    hot_sectors_html = "".join(hot_sectors_items)

    # 3. 최근 공시 수집 및 카테고리별 분리 (캐싱 적용으로 빌드 속도 10배 가속)
    disc_cache_file = Path(__file__).parent / "data" / "web_disclosure_cache.json"
    disc_cache = {}
    if disc_cache_file.exists():
        try:
            with open(disc_cache_file, 'r', encoding='utf-8') as f:
                disc_cache = json.load(f)
        except Exception:
            disc_cache = {}

    cached_seen = disc_cache.get('seen', [])
    earnings_cards = [
        c.replace("| YoY ", "| 전년동기대비(YoY) ")
         .replace("| QoQ ", "| 직전분기대비(QoQ) ")
         .replace("(컨센 ", "(증권가예상치 ")
         .replace("(시장예상치 ", "(증권가예상치 ")
         .replace("컨센 부합", "증권가 예상치 부합")
         .replace("(컨센서스 없음)", "(증권가 예상치 없음)")
         .replace("[YoY ", "[전년동기대비 ")
        for c in disc_cache.get('earnings_cards', [])
    ]
    buyback_cards = disc_cache.get('buyback_cards', [])
    ir_cards = disc_cache.get('ir_cards', [])

    def render_disc_card(block, badge_class, badge_label, card_type):
        b = block.replace('<a href=', '<a target="_blank" rel="noopener noreferrer" href=')
        is_burn = '소각' in b
        is_watch = '⭐' in b or is_burn
        b_clean = b.replace('⭐', '').strip()
        lines = [l.strip() for l in b_clean.split('\n') if l.strip()]
        if not lines:
            return ""
        header_text = lines[0]
        details_html = ""
        if len(lines) > 1:
            details_joined = "<br>".join(lines[1:])
            details_html = f"<div class='card-details'>{details_joined}</div>"
        watch_tag = ""
        if is_burn:
            watch_tag = '<span class="watch-tag tag-burn">🔥 초특급 소각</span>'
        elif is_watch:
            if "어닝서프라이즈" in b:
                watch_tag = '<span class="watch-tag tag-surprise">⭐ 어닝 서프라이즈</span>'
            elif "흑자전환" in b:
                watch_tag = '<span class="watch-tag tag-turnaround">⭐ 흑자전환</span>'
            elif "YoY +" in b:
                watch_tag = '<span class="watch-tag tag-growth">⭐ 실적 급증</span>'
            elif "자사주" in b:
                watch_tag = '<span class="watch-tag tag-buyback">⭐ 대규모 자사주(100억+)</span>'
            else:
                watch_tag = '<span class="watch-tag">⭐ 핵심 포착</span>'
        watch_card_class = " is-burn" if is_burn else (" is-watchlist" if is_watch else "")
        return f"""
        <div class="disclosure-card {card_type}{watch_card_class}">
            <div class="card-top-row">
                <span class="badge {badge_class}">{badge_label}</span>
                {watch_tag}
            </div>
            <div class="card-main-title">{header_text}</div>
            {details_html}
        </div>
        """

    try:
        from dotenv import load_dotenv
        load_dotenv()
        api_key = os.getenv('DART_API_KEY')
        if api_key:
            from src import disclosure as d
            dart = d.Dart(api_key)
            temp_state = {'seen': list(cached_seen), 'ir_dates': {}}
            watch = d.load_watchlist()
            sections = d.collect_new_disclosures(dart, temp_state, watch, max_items=20)
            if sections:
                new_burn, new_earn, new_buy, new_ir = [], [], [], []
                for title, blocks in sections:
                    if "소각" in title:
                        for block in blocks:
                            card = render_disc_card(block, "badge-fire", "🔥 주식소각", "type-burn")
                            if card:
                                new_burn.append(card)
                    elif "실적" in title:
                        for block in blocks:
                            card = render_disc_card(block, "badge-green", "📈 실적공시", "type-earnings")
                            if card:
                                new_earn.append(card)
                    elif "자사주" in title:
                        for block in blocks:
                            card = render_disc_card(block, "badge-gold", "💰 자사주(100억+)", "type-buyback")
                            if card:
                                new_buy.append(card)
                    elif "IR" in title:
                        for block in blocks:
                            card = render_disc_card(block, "badge-purple", "🎤 IR일정", "type-ir")
                            if card:
                                new_ir.append(card)

                buyback_cards = new_burn + new_buy + buyback_cards
                earnings_cards = new_earn + earnings_cards
                ir_cards = new_ir + ir_cards

            # 캐시 업데이트 (최대 30개 유지)
            disc_cache['seen'] = list(set(temp_state['seen']))[-300:]
            disc_cache['buyback_cards'] = buyback_cards[:30]
            disc_cache['earnings_cards'] = earnings_cards[:30]
            disc_cache['ir_cards'] = ir_cards[:30]
            try:
                disc_cache_file.parent.mkdir(exist_ok=True)
                with open(disc_cache_file, 'w', encoding='utf-8') as f:
                    json.dump(disc_cache, f, ensure_ascii=False, indent=2)
            except Exception as e:
                print(f"공시 캐시 저장 실패: {e}")
    except Exception as e:
        print(f"공시 수집 중 오류: {e}")

    earnings_count = len(earnings_cards)
    buyback_count = len(buyback_cards)
    ir_count = len(ir_cards)
    total_disc_count = earnings_count + buyback_count + ir_count

    earnings_html = "".join(earnings_cards)
    buyback_html = "".join(buyback_cards)
    ir_html = "".join(ir_cards)

    # 지표 카드 도우미
    def format_ratio(val):
        if val > 0:
            return f"<span class='up'>+{val:.2f}% 🔺</span>"
        elif val < 0:
            return f"<span class='down'>{val:.2f}% 🔻</span>"
        return f"<span>{val:.2f}% ➖</span>"

    fut_display = f"{fut_price:,.1f}" if fut_price else "-"
    fut_badge = format_ratio(fut_ratio)

    sox_display = sox_close or "-"
    sox_badge = format_ratio(sox_ratio)

    nas_display = nas_close or "-"
    nas_badge = format_ratio(nas_ratio)

    fx_display = f"{fx_close}원" if fx_close else "-"
    fx_badge = format_ratio(fx_ratio)

    kp_display = kp_close or "-"
    kp_badge = format_ratio(kp_ratio)

    kd_display = kd_close or "-"
    kd_badge = format_ratio(kd_ratio)

    vix_display = vix_close or "-"
    vix_badge = format_ratio(vix_ratio) if vix_close else "<span>-</span>"

    us10y_display = f"{us10y_price:.2f}%" if us10y_price else "-"
    if us10y_diff and us10y_diff > 0:
        us10y_badge = f"<span class='up'>+{us10y_diff:.2f}%p 🔺</span>"
    elif us10y_diff and us10y_diff < 0:
        us10y_badge = f"<span class='down'>{us10y_diff:.2f}%p 🔻</span>"
    else:
        us10y_badge = "<span>0.00%p ➖</span>"

    # 8대 시장 지표별 호재/악재 판정 배지 및 실전 영향 설명문 산출
    # 1) E-mini 나스닥100 선물
    if fut_ratio >= 0.5:
        fut_impact_badge = '<span class="impact-badge impact-good">🟢 강력 호재</span>'
        fut_impact_desc = "야간 미 증시 랠리 지속. 내일 아침 국내 증시 시초가 갭상승 출발 기대"
    elif fut_ratio >= 0.0:
        fut_impact_badge = '<span class="impact-badge impact-good">🟢 호재 (상승)</span>'
        fut_impact_desc = "미 선물 완만한 상승. 내일 국내 시초가 안정적 방어 및 강보합 출발 우호적"
    elif fut_ratio >= -0.5:
        fut_impact_badge = '<span class="impact-badge impact-neutral">⚪ 중립 (약보합)</span>'
        fut_impact_desc = "미 선물 소폭 하락. 시초가 보합권 출발 예상, 장초반 외인 매매 확인 필요"
    else:
        fut_impact_badge = '<span class="impact-badge impact-bad">🔴 악재 (하락주의)</span>'
        fut_impact_desc = "야간 미 선물 급락. 내일 아침 시초가 갭하락 및 하방 매물 출회 주의"

    # 2) 필라델피아 반도체 지수
    if sox_ratio >= 1.0:
        sox_impact_badge = '<span class="impact-badge impact-good">🟢 강력 호재</span>'
        sox_impact_desc = "미 반도체 급등. 삼성전자, SK하이닉스 및 국내 소부장 테마 강한 상승 견인"
    elif sox_ratio > 0.0:
        sox_impact_badge = '<span class="impact-badge impact-good">🟢 호재 (상승)</span>'
        sox_impact_desc = "글로벌 IT 섹터 호조. 국내 반도체 대형주 중심 지수 상승 분위기 조성"
    elif sox_ratio >= -1.0:
        sox_impact_badge = '<span class="impact-badge impact-neutral">⚪ 중립 (보합)</span>'
        sox_impact_desc = "반도체 지수 소폭 조정. 섹터 전체보다 실적 우량 개별 소부장주 차별화"
    else:
        sox_impact_badge = '<span class="impact-badge impact-bad">🔴 악재 (하락압력)</span>'
        sox_impact_desc = "미 반도체 급락. 국내 반도체 대형주 하방 압력으로 지수 전반 위축 가능성"

    # 3) 코스피 & 수급
    kp_num = kp_for_num if kp_for_num is not None else 0
    if kp_num >= 1000:
        kp_impact_badge = '<span class="impact-badge impact-good">🟢 순매수 (호재)</span>'
        kp_impact_desc = "외국인이 지수를 견인 중. 코스피 대형주 및 지수 전반의 상승 탄력 강화"
    elif kp_num >= 0:
        kp_impact_badge = '<span class="impact-badge impact-neutral">⚪ 매수 우위</span>'
        kp_impact_desc = "외국인 소폭 순매수. 하방 경직성을 확보하며 안정적인 지수 흐름 뒷받침"
    elif kp_num >= -1000:
        kp_impact_badge = '<span class="impact-badge impact-caution">🟡 주의 (매도)</span>'
        kp_impact_desc = "외국인 단기 차익 실현. 지수 상단 제한, 순환매 및 방어적 대응 유리"
    else:
        kp_impact_badge = '<span class="impact-badge impact-bad">🔴 악재 (외인 이탈)</span>'
        kp_impact_desc = "외국인 대규모 매도세. 대형주 중심 지수 하방 압력 지속, 무리한 추격매수 자제"

    # 4) 코스닥 & 수급
    kd_num = kd_for_num if kd_for_num is not None else 0
    if kd_num >= 500:
        kd_impact_badge = '<span class="impact-badge impact-good">🟢 순매수 (호재)</span>'
        kd_impact_desc = "외인 매수세 유입. 바이오, 2차전지, AI 등 성장 테마주의 탄력적인 슈팅 기대"
    elif kd_num >= 0:
        kd_impact_badge = '<span class="impact-badge impact-neutral">⚪ 수급 안정</span>'
        kd_impact_desc = "외인 수급 균형. 테마주 종가베팅 시 비교적 양호한 성공 확률 기대"
    elif kd_num >= -500:
        kd_impact_badge = '<span class="impact-badge impact-caution">🟡 주의 (차익실현)</span>'
        kd_impact_desc = "외인 차익 실현 중. 개별 호재 및 실적 모멘텀이 확실한 주도주로 압축 대응"
    else:
        kd_impact_badge = '<span class="impact-badge impact-bad">🔴 악재 (매도압력)</span>'
        kd_impact_desc = "외인 강한 매도세. 코스닥 중소형주 변동성 확대, 종가베팅 비중 축소 권장"

    # 5) 원/달러 환율 (환율 하락 = 원화 강세 = 호재)
    if fx_ratio <= -0.3:
        fx_impact_badge = '<span class="impact-badge impact-good">🟢 원화강세 (호재)</span>'
        fx_impact_desc = "환율 하락으로 외인 환차익 매력 증가. 국내 증시 외국인 자금 유입 촉진"
    elif fx_ratio <= 0.2:
        fx_impact_badge = '<span class="impact-badge impact-neutral">⚪ 환율 안정</span>'
        fx_impact_desc = "환율 등락폭 제한적. 외국인 수급에 특별한 이탈 압력 없이 중립적 작용"
    elif fx_ratio <= 0.7:
        fx_impact_badge = '<span class="impact-badge impact-caution">🟡 주의 (환율상승)</span>'
        fx_impact_desc = "원화 약세 진행 중. 외국인 매수세 유입이 제한되고 관망세가 짙어질 수 있음"
    else:
        fx_impact_badge = '<span class="impact-badge impact-bad">🔴 악재 (환율급등)</span>'
        fx_impact_desc = "환율 급등으로 외인 환차손 회피 투매 위험. 외국인 자금 이탈 경계 필요"

    # 6) CNN 공포 & 탐욕 지수
    if cnn_score <= 25:
        cnn_impact_badge = '<span class="impact-badge impact-caution">🟡 극단적 공포 (반등기회)</span>'
        cnn_impact_desc = "시장 공포 극대화 구간. 단기 투매 위험 있으나 역발상 저가 매수세/기술적 반등 임박"
    elif cnn_score <= 45:
        cnn_impact_badge = '<span class="impact-badge impact-caution">🟡 공포 (조정구간)</span>'
        cnn_impact_desc = "투자 심리 위축. 시장에 불안감이 팽배한 상태로 우량주 분할 매수 고려 영역"
    elif cnn_score <= 55:
        cnn_impact_badge = '<span class="impact-badge impact-neutral">⚪ 중립 (균형상태)</span>'
        cnn_impact_desc = "공포와 탐욕 균형. 매크로 충격보다 개별 종목 재료와 실적에 정직하게 반응"
    elif cnn_score <= 75:
        cnn_impact_badge = '<span class="impact-badge impact-good">🟢 호재 (낙관적 탐욕)</span>'
        cnn_impact_desc = "투자 심리 강세. 지수 상승 탄력이 좋고 종가베팅 성공 확률이 높은 우호적 환경"
    else:
        cnn_impact_badge = '<span class="impact-badge impact-bad">🔴 주의 (극단적 탐욕/과열)</span>'
        cnn_impact_desc = "시장 과열 극치. 누구나 수익 중인 위험 구간, 차익 매물 출회 및 고점 상투 경계"

    # 7) VIX 변동성 지수
    vix_val = None
    if vix_close:
        try:
            vix_val = float(str(vix_close).replace(',', ''))
        except Exception:
            vix_val = None

    if vix_val is not None:
        if vix_val < 18:
            vix_impact_badge = '<span class="impact-badge impact-good">🟢 안정 (호재)</span>'
            vix_impact_desc = "월가 공포가 매우 낮고 안정적. 급락 위험이 적어 종가베팅 및 오버나잇 유리"
        elif vix_val < 23:
            vix_impact_badge = '<span class="impact-badge impact-neutral">⚪ 보통 (정상범위)</span>'
            vix_impact_desc = "통상적인 변동성 수준. 시스템 리스크 없이 테마주와 지수가 정상적으로 전개"
        elif vix_val < 30:
            vix_impact_badge = '<span class="impact-badge impact-caution">🟡 경계 (변동성확대)</span>'
            vix_impact_desc = "월가 불안감 급증. 지수 등락폭이 커지고 장중 변동성이 심하므로 목표수익 짧게 대응"
        else:
            vix_impact_badge = '<span class="impact-badge impact-bad">🔴 악재 (패닉셀위험)</span>'
            vix_impact_desc = "시장 패닉 상태(30 이상). 지수 급락 및 투매 발생 위험 높아 현금 비중 확대 필수"
    else:
        vix_impact_badge = '<span class="impact-badge impact-neutral">⚪ 데이터 대기</span>'
        vix_impact_desc = "월가 공포지수 수집 대기 중"

    # 8) 미국 10년물 국채금리
    if us10y_diff is not None and us10y_diff <= -0.03:
        us10y_impact_badge = '<span class="impact-badge impact-good">🟢 호재 (금리하락)</span>'
        us10y_impact_desc = "글로벌 긴축 완화 신호. 기술주, 2차전지, 바이오 등 성장주 밸류에이션 부담 완화"
    elif us10y_diff is not None and abs(us10y_diff) < 0.03:
        us10y_impact_badge = '<span class="impact-badge impact-neutral">⚪ 보합 (금리안정)</span>'
        us10y_impact_desc = "채권 금리 안정세. 주식 시장 밸류에이션에 미치는 영향이 중립적"
    elif us10y_diff is not None and us10y_diff > 0.03:
        us10y_impact_badge = '<span class="impact-badge impact-bad">🔴 악재 (금리급등)</span>'
        us10y_impact_desc = "고금리 긴축 우려 재부각. 유동성 축소로 성장주 및 기술주에 주가 하방 압력"
    else:
        us10y_impact_badge = '<span class="impact-badge impact-neutral">⚪ 보합</span>'
        us10y_impact_desc = "글로벌 벤치마크 금리가 기준선 부근에서 안정적인 흐름 유지"

    # 현재 시간대별 기본 활성 가이드 탭 자동 매칭 (아침/정규장/마감/야간)
    if 700 <= hm_kst < 815:
        def_guide_key, def_guide_idx = 'g0740', 0
    elif 815 <= hm_kst < 1300:
        def_guide_key, def_guide_idx = 'g0840', 1
    elif 1300 <= hm_kst < 1700:
        def_guide_key, def_guide_idx = 'g1510', 2
    else:
        def_guide_key, def_guide_idx = 'g1940', 3

    t0_act = ' active' if def_guide_idx == 0 else ''
    t1_act = ' active' if def_guide_idx == 1 else ''
    t2_act = ' active' if def_guide_idx == 2 else ''
    t3_act = ' active' if def_guide_idx == 3 else ''

    # HTML 템플릿
    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
    <meta http-equiv="Pragma" content="no-cache">
    <meta http-equiv="Expires" content="0">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>비니stock 실전 트레이딩 대시보드</title>
    <meta name="description" content="E-mini 나스닥 100 선물, 외인/기관 수급, 종가베팅 & 시초가 매도 타이밍 실시간 분석 대시보드">
    <link rel="manifest" href="manifest.json">
    <meta name="theme-color" content="#0b0f19">
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Pretendard:wght@400;600;700;800&family=JetBrains+Mono:wght@500;700&display=swap" rel="stylesheet">
    <style>
        :root {{
            --bg: #0b0f19;
            --surface: #111827;
            --surface-hover: #1f2937;
            --border: rgba(255, 255, 255, 0.08);
            --text-main: #f9fafb;
            --text-sub: #9ca3af;
            --primary: #3b82f6;
            --up: #ef4444;
            --down: #3b82f6;
            --green: #10b981;
            --gold: #f59e0b;
            --purple: #8b5cf6;
        }}
        [data-theme="light"] {{
            --bg: #f8fafc;
            --surface: #ffffff;
            --surface-hover: #f1f5f9;
            --border: rgba(0, 0, 0, 0.09);
            --text-main: #0f172a;
            --text-sub: #475569;
            --primary: #2563eb;
        }}
        [data-theme="light"] body {{
            background: #f8fafc;
            color: #0f172a;
        }}
        [data-theme="light"] .metric-card,
        [data-theme="light"] .rec-card,
        [data-theme="light"] .disclosure-card,
        [data-theme="light"] .guide-card,
        [data-theme="light"] .criteria-card,
        [data-theme="light"] .swing-sim-card,
        [data-theme="light"] .risk-banner-card {{
            background: #ffffff;
            border-color: rgba(0, 0, 0, 0.1);
            box-shadow: 0 4px 14px rgba(0, 0, 0, 0.05);
        }}
        [data-theme="light"] .card-main-title,
        [data-theme="light"] .card-main-title a,
        [data-theme="light"] .card-main-title b {{
            color: #0f172a !important;
        }}
        [data-theme="light"] .card-details {{
            background: #f1f5f9;
            color: #1e293b !important;
            border-color: rgba(0, 0, 0, 0.06);
        }}
        [data-theme="light"] .rec-stock-title a {{
            color: #0f172a;
        }}
        [data-theme="light"] .rec-desc-box {{
            background: #f8fafc;
        }}
        [data-theme="light"] .rec-desc-title {{
            color: #334155;
        }}
        [data-theme="light"] .rec-desc-text {{
            color: #1e293b;
        }}
        [data-theme="light"] .sim-table th {{
            background: #f1f5f9;
            color: #334155;
        }}
        [data-theme="light"] .sim-table td {{
            border-bottom-color: rgba(0, 0, 0, 0.06);
            color: #1e293b;
        }}
        [data-theme="light"] .sim-stock-cell b {{
            color: #0f172a;
        }}
        [data-theme="light"] .criteria-item {{
            background: #f8fafc;
        }}
        [data-theme="light"] .ci-title {{
            color: #0f172a;
        }}
        [data-theme="light"] .ci-desc {{
            color: #475569;
        }}
        .header-right-controls {{
            display: flex;
            align-items: center;
            gap: 10px;
            flex-wrap: wrap;
        }}
        .toolbar-btn {{
            background: rgba(255, 255, 255, 0.06);
            color: var(--text-main);
            border: 1px solid var(--border);
            padding: 6px 12px;
            border-radius: 999px;
            font-size: 0.8rem;
            font-weight: 600;
            cursor: pointer;
            display: flex;
            align-items: center;
            gap: 6px;
            transition: all 0.2s;
        }}
        .toolbar-btn:hover {{
            background: rgba(255, 255, 255, 0.12);
            border-color: rgba(255, 255, 255, 0.2);
            transform: translateY(-1px);
        }}
        .toolbar-btn.refresh-btn {{
            background: rgba(16, 185, 129, 0.15);
            color: #34d399;
            border-color: rgba(16, 185, 129, 0.35);
        }}
        .toolbar-btn.refresh-btn:hover {{
            background: rgba(16, 185, 129, 0.28);
            border-color: #34d399;
            box-shadow: 0 0 12px rgba(16, 185, 129, 0.3);
        }}
        .toolbar-btn.cloud-btn {{
            background: rgba(59, 130, 246, 0.15);
            color: #60a5fa;
            border-color: rgba(59, 130, 246, 0.35);
        }}
        .toolbar-btn.cloud-btn:hover {{
            background: rgba(59, 130, 246, 0.28);
            border-color: #60a5fa;
            box-shadow: 0 0 12px rgba(59, 130, 246, 0.3);
        }}
        .risk-quick-refresh-btn {{
            background: rgba(255, 255, 255, 0.08);
            color: var(--text-main);
            border: 1px solid var(--border);
            padding: 3px 10px;
            border-radius: 999px;
            font-size: 0.74rem;
            font-weight: 700;
            cursor: pointer;
            margin-left: 8px;
            transition: all 0.2s;
        }}
        .risk-quick-refresh-btn:hover {{
            background: rgba(255, 255, 255, 0.18);
            color: #34d399;
            border-color: #34d399;
        }}
        .spin {{
            display: inline-block;
            animation: spinAnim 1s linear infinite;
        }}
        @keyframes spinAnim {{
            from {{ transform: rotate(0deg); }}
            to {{ transform: rotate(360deg); }}
        }}
        /* 클라우드 모달 스타일 */
        .modal-overlay {{
            position: fixed;
            top: 0; left: 0; right: 0; bottom: 0;
            background: rgba(0, 0, 0, 0.75);
            backdrop-filter: blur(6px);
            z-index: 9999;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 16px;
        }}
        .modal-content {{
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 16px;
            max-width: 520px;
            width: 100%;
            box-shadow: 0 20px 40px rgba(0, 0, 0, 0.6);
            overflow: hidden;
            animation: modalFadeIn 0.25s ease-out;
        }}
        @keyframes modalFadeIn {{
            from {{ opacity: 0; transform: scale(0.95); }}
            to {{ opacity: 1; transform: scale(1); }}
        }}
        .modal-header {{
            padding: 16px 20px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid var(--border);
        }}
        .modal-header h3 {{
            margin: 0;
            font-size: 1.05rem;
            font-weight: 700;
            color: var(--text-main);
        }}
        .modal-close {{
            background: none;
            border: none;
            color: var(--text-sub);
            font-size: 1.3rem;
            cursor: pointer;
            padding: 4px;
            line-height: 1;
        }}
        .modal-body {{
            padding: 18px 20px;
            max-height: 80vh;
            overflow-y: auto;
        }}
        .modal-desc {{
            font-size: 0.85rem;
            color: var(--text-sub);
            line-height: 1.55;
            margin-bottom: 14px;
        }}
        .cloud-action-card {{
            background: rgba(255, 255, 255, 0.03);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 12px 14px;
            margin-bottom: 12px;
        }}
        .cac-title {{
            font-size: 0.88rem;
            font-weight: 700;
            color: var(--text-main);
            margin-bottom: 4px;
        }}
        .cac-desc {{
            font-size: 0.78rem;
            color: var(--text-sub);
            line-height: 1.45;
            margin-bottom: 8px;
        }}
        .cac-btn {{
            display: inline-flex;
            align-items: center;
            justify-content: center;
            gap: 6px;
            width: 100%;
            padding: 9px 14px;
            border-radius: 8px;
            font-size: 0.85rem;
            font-weight: 700;
            text-decoration: none;
            cursor: pointer;
            border: none;
            box-sizing: border-box;
            transition: all 0.2s;
        }}
        .cac-btn.primary {{
            background: linear-gradient(135deg, #2563eb, #3b82f6);
            color: #ffffff;
        }}
        .cac-btn.primary:hover {{
            background: #1d4ed8;
            box-shadow: 0 4px 12px rgba(37, 99, 235, 0.4);
        }}
        .cac-btn.green {{
            background: #10b981;
            color: #ffffff;
            width: auto;
            white-space: nowrap;
        }}
        .token-input-row {{
            display: flex;
            gap: 8px;
        }}
        .token-input {{
            flex: 1;
            background: rgba(0, 0, 0, 0.3);
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 8px 12px;
            color: var(--text-main);
            font-size: 0.82rem;
        }}
        .token-status {{
            font-size: 0.76rem;
            margin-top: 6px;
            min-height: 16px;
        }}
        .cloud-schedule-box {{
            background: rgba(59, 130, 246, 0.05);
            border: 1px solid rgba(59, 130, 246, 0.2);
            border-radius: 12px;
            padding: 12px 14px;
            font-size: 0.8rem;
        }}
        .csb-title {{
            font-weight: 700;
            color: #60a5fa;
            margin-bottom: 4px;
        }}
        .cloud-schedule-box ul {{
            margin: 0;
            padding-left: 18px;
            color: var(--text-main);
            line-height: 1.65;
        }}
        .csb-sub {{
            margin-top: 6px;
            font-size: 0.74rem;
            color: var(--text-sub);
        }}
        .quick-etf-bar {{
            display: flex;
            align-items: center;
            gap: 6px;
            margin-top: 6px;
            flex-wrap: wrap;
        }}
        .quick-label {{
            font-size: 0.74rem;
            color: var(--text-sub);
            font-weight: 600;
        }}
        .quick-tag {{
            font-size: 0.72rem;
            font-weight: 700;
            padding: 2px 7px;
            border-radius: 4px;
            background: rgba(59, 130, 246, 0.12);
            color: #60a5fa;
            border: 1px solid rgba(59, 130, 246, 0.25);
            text-decoration: none;
            transition: all 0.15s;
        }}
        .quick-tag:hover {{
            background: #2563eb;
            color: #ffffff;
        }}
        .risk-banner-card {{
            background: linear-gradient(135deg, rgba(17, 24, 39, 0.95), rgba(15, 23, 42, 0.98));
            border: 1px solid var(--border);
            border-radius: 14px;
            padding: 16px 20px;
            margin-bottom: 24px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 16px;
            box-shadow: 0 4px 20px rgba(0, 0, 0, 0.2);
            transition: all 0.3s;
        }}
        .risk-good {{ border-left: 5px solid #10b981; }}
        .risk-caution {{ border-left: 5px solid #f59e0b; }}
        .risk-danger {{ border-left: 5px solid #ef4444; }}
        .risk-left {{ flex: 1; min-width: 280px; }}
        .risk-title-row {{
            display: flex;
            align-items: center;
            gap: 10px;
            margin-bottom: 6px;
            flex-wrap: wrap;
        }}
        .risk-icon-pill {{ font-size: 0.92rem; font-weight: 800; color: var(--text-main); }}
        .risk-status-badge {{
            font-size: 0.78rem;
            font-weight: 800;
            padding: 3px 10px;
            border-radius: 999px;
            background: rgba(255, 255, 255, 0.08);
            border: 1px solid var(--border);
        }}
        .risk-good .risk-status-badge {{
            background: rgba(16, 185, 129, 0.18);
            color: #34d399;
            border-color: rgba(16, 185, 129, 0.4);
        }}
        .risk-caution .risk-status-badge {{
            background: rgba(245, 158, 11, 0.18);
            color: #fbbf24;
            border-color: rgba(245, 158, 11, 0.4);
        }}
        .risk-danger .risk-status-badge {{
            background: rgba(239, 68, 68, 0.18);
            color: #f87171;
            border-color: rgba(239, 68, 68, 0.4);
        }}
        .risk-desc-text {{ font-size: 0.85rem; color: var(--text-sub); line-height: 1.5; }}
        .risk-right {{
            display: flex;
            flex-direction: column;
            align-items: flex-end;
            min-width: 180px;
            gap: 6px;
        }}
        .risk-score-display {{ display: flex; align-items: baseline; gap: 4px; }}
        .risk-score-num {{
            font-family: 'JetBrains Mono', monospace;
            font-size: 2rem;
            font-weight: 800;
            line-height: 1;
            color: var(--text-main);
        }}
        .risk-score-unit {{ font-size: 0.85rem; color: var(--text-sub); }}
        .risk-meter-bar-container {{
            width: 180px;
            height: 8px;
            background: rgba(255, 255, 255, 0.1);
            border-radius: 999px;
            overflow: hidden;
        }}
        .risk-meter-bar-fill {{ height: 100%; border-radius: 999px; transition: width 0.5s ease; }}
        .marcap-filter-bar {{
            display: flex;
            align-items: center;
            gap: 8px;
            margin: 16px 0 20px;
            flex-wrap: wrap;
            padding: 10px 14px;
            background: rgba(255, 255, 255, 0.03);
            border: 1px solid var(--border);
            border-radius: 10px;
        }}
        .mfilter-label {{ font-size: 0.82rem; font-weight: 700; color: var(--text-sub); margin-right: 4px; }}
        .mfilter-btn {{
            background: rgba(255, 255, 255, 0.05);
            border: 1px solid var(--border);
            color: var(--text-sub);
            padding: 5px 12px;
            border-radius: 6px;
            font-size: 0.8rem;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
        }}
        .mfilter-btn:hover {{ background: rgba(255, 255, 255, 0.1); color: var(--text-main); }}
        .mfilter-btn.active {{
            background: #2563eb;
            color: #ffffff;
            border-color: #3b82f6;
            box-shadow: 0 0 10px rgba(37, 99, 235, 0.4);
        }}
        .swing-sim-card {{
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 14px;
            padding: 20px;
            margin-top: 24px;
            margin-bottom: 24px;
            box-shadow: 0 4px 20px rgba(0, 0, 0, 0.2);
        }}
        .swing-sim-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 16px;
            flex-wrap: wrap;
            gap: 10px;
        }}
        .swing-sim-header h3 {{ font-size: 1.05rem; font-weight: 800; color: var(--text-main); margin-bottom: 4px; }}
        .sim-desc {{ font-size: 0.82rem; color: var(--text-sub); }}
        .sim-badge {{
            font-size: 0.72rem;
            font-weight: 700;
            padding: 3px 8px;
            border-radius: 999px;
            background: rgba(139, 92, 246, 0.15);
            color: #c084fc;
            border: 1px solid rgba(139, 92, 246, 0.35);
        }}
        .table-responsive {{ overflow-x: auto; -webkit-overflow-scrolling: touch; }}
        .sim-table {{ width: 100%; border-collapse: collapse; font-size: 0.85rem; text-align: left; }}
        .sim-table th {{
            padding: 10px 12px;
            background: rgba(255, 255, 255, 0.04);
            color: var(--text-sub);
            font-weight: 600;
            border-bottom: 1px solid var(--border);
            white-space: nowrap;
        }}
        .sim-table td {{ padding: 12px; border-bottom: 1px solid var(--border); white-space: nowrap; }}
        .sim-stock-cell b {{ color: var(--text-main); font-size: 0.92rem; }}
        .sim-code {{ font-size: 0.78rem; color: var(--text-sub); font-family: 'JetBrains Mono', monospace; margin-left: 4px; }}
        .sim-price-cell {{ font-weight: 700; color: var(--text-main); }}
        .sim-val {{ font-weight: 700; margin-right: 6px; }}
        .sim-pct {{ font-size: 0.72rem; font-weight: 700; padding: 2px 6px; border-radius: 4px; }}
        .badge-blue {{ background: rgba(59, 130, 246, 0.18); color: #93c5fd; }}
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            background: var(--bg);
            color: var(--text-main);
            font-family: 'Pretendard', -apple-system, sans-serif;
            padding: 16px 24px;
            max-width: 1560px;
            width: 96%;
            margin: 0 auto;
            line-height: 1.5;
        }}
        header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 16px 0 24px;
            border-bottom: 1px solid var(--border);
            margin-bottom: 24px;
            flex-wrap: wrap;
            gap: 12px;
        }}
        .logo-area h1 {{
            font-size: 1.5rem;
            font-weight: 800;
            background: linear-gradient(135deg, #60a5fa, #a78bfa);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            display: flex;
            align-items: center;
            gap: 8px;
        }}
        .time-badge {{
            font-size: 0.82rem;
            color: var(--text-sub);
            font-family: 'JetBrains Mono', monospace;
            background: rgba(255,255,255,0.05);
            padding: 6px 12px;
            border-radius: 999px;
            border: 1px solid var(--border);
        }}
        .live-dot {{
            display: inline-block;
            width: 8px;
            height: 8px;
            background: #10b981;
            border-radius: 50%;
            margin-right: 6px;
            box-shadow: 0 0 10px #10b981;
            animation: pulse 2s infinite;
        }}
        @keyframes pulse {{
            0% {{ transform: scale(0.95); opacity: 0.7; }}
            50% {{ transform: scale(1.2); opacity: 1; }}
            100% {{ transform: scale(0.95); opacity: 0.7; }}
        }}

        /* 지표 그리드 */
        .grid-indicators {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
            gap: 14px;
            margin-bottom: 28px;
        }}
        .metric-card {{
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 14px;
            padding: 16px;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
            transition: transform 0.2s, border-color 0.2s, box-shadow 0.2s;
        }}
        .metric-card:hover {{
            border-color: rgba(255,255,255,0.22);
            transform: translateY(-2px);
            box-shadow: 0 8px 24px rgba(0, 0, 0, 0.35);
        }}
        .metric-top-row {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 8px;
            gap: 6px;
        }}
        .metric-label {{
            font-size: 0.82rem;
            color: var(--text-sub);
            font-weight: 600;
            display: flex;
            align-items: center;
            gap: 6px;
        }}
        .impact-badge {{
            font-size: 0.72rem;
            font-weight: 700;
            padding: 2px 8px;
            border-radius: 999px;
            white-space: nowrap;
        }}
        .impact-good {{
            background: rgba(16, 185, 129, 0.15);
            color: #34d399;
            border: 1px solid rgba(16, 185, 129, 0.35);
        }}
        .impact-bad {{
            background: rgba(239, 68, 68, 0.15);
            color: #f87171;
            border: 1px solid rgba(239, 68, 68, 0.35);
        }}
        .impact-caution {{
            background: rgba(245, 158, 11, 0.15);
            color: #fbbf24;
            border: 1px solid rgba(245, 158, 11, 0.35);
        }}
        .impact-neutral {{
            background: rgba(156, 163, 175, 0.15);
            color: #e5e7eb;
            border: 1px solid rgba(156, 163, 175, 0.3);
        }}
        .metric-main-row {{
            display: flex;
            align-items: baseline;
            justify-content: space-between;
            margin-bottom: 2px;
        }}
        .metric-value {{
            font-size: 1.4rem;
            font-weight: 800;
            font-family: 'JetBrains Mono', monospace;
            color: #ffffff;
        }}
        .live-quote-link {{
            font-size: 0.72rem;
            font-weight: 700;
            color: #60a5fa;
            background: rgba(59, 130, 246, 0.12);
            border: 1px solid rgba(59, 130, 246, 0.3);
            border-radius: 6px;
            padding: 2px 8px;
            text-decoration: none;
            transition: all 0.2s;
            margin-left: 6px;
            white-space: nowrap;
            display: inline-flex;
            align-items: center;
            gap: 3px;
        }}
        .live-quote-link:hover {{
            background: #2563eb;
            color: #ffffff;
            border-color: #2563eb;
        }}
        .up {{ color: #f87171; }}
        .down {{ color: #60a5fa; }}
        .metric-sub {{
            font-size: 0.78rem;
            color: var(--text-sub);
            margin-bottom: 10px;
        }}
        .metric-desc {{
            background: rgba(0, 0, 0, 0.32);
            border: 1px solid rgba(255, 255, 255, 0.06);
            border-radius: 8px;
            padding: 9px 11px;
            font-size: 0.78rem;
            line-height: 1.45;
            color: #d1d5db;
            margin-top: auto;
        }}
        .metric-desc-title {{
            color: #9ca3af;
            font-weight: 700;
            font-size: 0.72rem;
            margin-bottom: 3px;
            display: flex;
            align-items: center;
            gap: 4px;
        }}
        .metric-desc-text {{
            color: #f3f4f6;
        }}

        /* 섹션 제목 */
        .section-title {{
            font-size: 1.15rem;
            font-weight: 700;
            margin: 28px 0 14px;
            display: flex;
            align-items: center;
            gap: 8px;
        }}

        /* AI 시장 안전도 레짐 배너 */
        .rec-market-alert {{
            border-radius: 14px;
            padding: 14px 18px;
            margin-bottom: 18px;
            display: flex;
            flex-direction: column;
            gap: 6px;
            border: 1px solid var(--border);
            transition: all 0.2s;
        }}
        .regime-warning {{
            background: rgba(239, 68, 68, 0.12);
            border-color: rgba(239, 68, 68, 0.4);
        }}
        .regime-bull {{
            background: rgba(16, 185, 129, 0.12);
            border-color: rgba(16, 185, 129, 0.4);
        }}
        .regime-neutral {{
            background: rgba(59, 130, 246, 0.08);
            border-color: rgba(59, 130, 246, 0.28);
        }}
        .regime-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 8px;
        }}
        .regime-badge {{
            font-size: 0.95rem;
            font-weight: 800;
        }}
        .regime-advice {{
            font-size: 0.82rem;
            color: #d1d5db;
        }}
        .regime-advice b {{
            color: #ffffff;
            background: rgba(255, 255, 255, 0.12);
            padding: 3px 9px;
            border-radius: 6px;
        }}
        .regime-msg {{
            font-size: 0.85rem;
            color: #f3f4f6;
            line-height: 1.55;
        }}

        /* 종목 발굴 기준 설명 카드 */
        .criteria-card {{
            background: rgba(255, 255, 255, 0.02);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 14px;
            padding: 16px 18px;
            margin-bottom: 18px;
        }}
        .criteria-head {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 8px;
            margin-bottom: 12px;
            padding-bottom: 8px;
            border-bottom: 1px solid rgba(255, 255, 255, 0.06);
            font-weight: 700;
            font-size: 0.95rem;
            color: #ffffff;
        }}
        .criteria-sub-tag {{
            font-size: 0.72rem;
            padding: 2px 8px;
            border-radius: 999px;
            background: rgba(59, 130, 246, 0.15);
            color: #60a5fa;
            border: 1px solid rgba(59, 130, 246, 0.3);
        }}
        .criteria-sub-tag.tag-purple {{
            background: rgba(139, 92, 246, 0.15);
            color: #c084fc;
            border-color: rgba(139, 92, 246, 0.3);
        }}
        .criteria-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
            gap: 12px;
        }}
        .criteria-item {{
            display: flex;
            gap: 10px;
            background: rgba(0, 0, 0, 0.25);
            border: 1px solid rgba(255, 255, 255, 0.04);
            border-radius: 10px;
            padding: 10px 12px;
        }}
        .ci-num {{
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.95rem;
            font-weight: 800;
            color: #f59e0b;
            flex-shrink: 0;
            line-height: 1.2;
            padding-top: 2px;
        }}
        .ci-num.num-purple {{
            color: #a78bfa;
        }}
        .ci-content {{
            display: flex;
            flex-direction: column;
            gap: 3px;
        }}
        .ci-title {{
            font-size: 0.84rem;
            font-weight: 700;
            color: #f9fafb;
        }}
        .ci-desc {{
            font-size: 0.76rem;
            color: #9ca3af;
            line-height: 1.45;
        }}

        /* AI 추천 종목 레이더 - 1줄 6칸 대형 카드형 네비게이션 */
        .rec-nav {{
            display: grid;
            grid-template-columns: repeat(6, minmax(0, 1fr));
            gap: 12px;
            width: 100%;
            margin-bottom: 18px;
        }}
        @media (max-width: 1220px) {{
            .rec-nav {{
                grid-template-columns: repeat(3, minmax(0, 1fr));
            }}
        }}
        @media (max-width: 680px) {{
            .rec-nav {{
                grid-template-columns: repeat(2, minmax(0, 1fr));
                gap: 8px;
            }}
        }}
        .rec-tab {{
            background: linear-gradient(180deg, rgba(31, 41, 55, 0.78), rgba(17, 24, 39, 0.95));
            border: 1.5px solid rgba(255, 255, 255, 0.11);
            border-top: 3px solid rgba(255, 255, 255, 0.2);
            color: var(--text-main);
            padding: 15px 10px;
            min-height: 84px;
            border-radius: 14px;
            cursor: pointer;
            display: flex;
            flex-direction: column;
            justify-content: center;
            align-items: center;
            text-align: center;
            gap: 8px;
            transition: all 0.22s ease;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.25);
        }}
        .rec-tab-title {{
            font-size: 1.0rem;
            font-weight: 800;
            color: #f3f4f6;
            letter-spacing: -0.02em;
            line-height: 1.25;
            white-space: nowrap;
        }}
        .rec-tab:hover {{
            transform: translateY(-2px);
            border-color: rgba(255, 255, 255, 0.32);
            background: linear-gradient(180deg, rgba(55, 65, 81, 0.85), rgba(31, 41, 55, 0.95));
            box-shadow: 0 8px 20px rgba(0, 0, 0, 0.38);
        }}
        .rec-tab.tab-amber {{ border-top-color: #f59e0b; }}
        .rec-tab.tab-purple {{ border-top-color: #8b5cf6; }}
        .rec-tab.tab-red {{ border-top-color: #ef4444; }}
        .rec-tab.tab-blue {{ border-top-color: #3b82f6; }}
        .rec-tab.tab-indigo {{ border-top-color: #a855f7; }}
        .rec-tab.tab-emerald {{ border-top-color: #10b981; }}
        .rec-tab.tab-cyan {{ border-top-color: #06b6d4; }}
        .rec-tab.tab-rose {{ border-top-color: #f43f5e; }}
        .rec-tab.tab-rose.active {{
            background: linear-gradient(135deg, rgba(244, 63, 94, 0.22), rgba(37, 99, 235, 0.22));
            border-color: #f43f5e;
            border-top: 3px solid #fb7185;
            box-shadow: 0 6px 20px rgba(244, 63, 94, 0.32);
        }}

        /* 실시간 머니플로우 전광판 (어웨이크형) 전용 CSS */
        .tmf-container {{
            display: flex;
            flex-direction: column;
            gap: 16px;
            margin-top: 6px;
        }}
        .tmf-hero-box {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 12px;
            padding: 16px 20px;
            background: linear-gradient(135deg, rgba(244, 63, 94, 0.14), rgba(30, 41, 59, 0.75));
            border: 1px solid rgba(244, 63, 94, 0.32);
            border-left: 4px solid #f43f5e;
            border-radius: 14px;
        }}
        .tmf-hero-title {{
            font-size: 1.05rem;
            font-weight: 800;
            color: #ffffff;
            display: flex;
            align-items: center;
            gap: 8px;
            flex-wrap: wrap;
        }}
        .tmf-live-badge {{
            font-size: 0.72rem;
            font-weight: 700;
            padding: 2px 8px;
            border-radius: 999px;
            background: rgba(244, 63, 94, 0.25);
            color: #fda4af;
            border: 1px solid rgba(244, 63, 94, 0.5);
        }}
        .tmf-hero-desc {{
            font-size: 0.8rem;
            color: #94a3b8;
            margin-top: 4px;
        }}
        .tmf-hero-right {{
            display: flex;
            flex-direction: column;
            align-items: flex-end;
            gap: 4px;
        }}
        .tmf-stat-badge {{
            font-size: 0.76rem;
            color: #cbd5e1;
            background: rgba(0, 0, 0, 0.35);
            padding: 4px 10px;
            border-radius: 8px;
            border: 1px solid rgba(255, 255, 255, 0.08);
        }}
        .tmf-filter-bar {{
            display: flex;
            gap: 8px;
            flex-wrap: wrap;
            margin-bottom: 2px;
        }}
        .tmf-filter-btn {{
            background: var(--surface);
            border: 1px solid var(--border);
            color: var(--text-sub);
            padding: 8px 14px;
            border-radius: 10px;
            font-size: 0.82rem;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
        }}
        .tmf-filter-btn:hover {{
            color: var(--text-main);
            border-color: rgba(255, 255, 255, 0.25);
        }}
        .tmf-filter-btn.active {{
            background: #2563eb;
            color: #fff;
            border-color: #3b82f6;
            box-shadow: 0 4px 12px rgba(37, 99, 235, 0.35);
        }}
        .tmf-filter-btn.tmf-btn-up.active {{
            background: #059669;
            border-color: #10b981;
            box-shadow: 0 4px 12px rgba(16, 185, 129, 0.35);
        }}
        .tmf-filter-btn.tmf-btn-down.active {{
            background: #dc2626;
            border-color: #ef4444;
            box-shadow: 0 4px 12px rgba(239, 68, 68, 0.35);
        }}
        .tmf-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(380px, 1fr));
            gap: 16px;
        }}
        @media (max-width: 768px) {{
            .tmf-grid {{
                grid-template-columns: 1fr;
            }}
            .tmf-hero-right {{
                align-items: flex-start;
            }}
        }}
        .tmf-card {{
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 14px;
            overflow: hidden;
            display: flex;
            flex-direction: column;
            box-shadow: 0 4px 16px rgba(0, 0, 0, 0.25);
            transition: transform 0.2s, box-shadow 0.2s;
        }}
        .tmf-card:hover {{
            transform: translateY(-2px);
            box-shadow: 0 8px 24px rgba(0, 0, 0, 0.35);
        }}
        .tmf-card.tmf-up {{
            border-top: 3px solid #10b981;
        }}
        .tmf-card.tmf-down {{
            border-top: 3px solid #3b82f6;
        }}
        .tmf-card-header {{
            padding: 12px 16px;
            background: rgba(0, 0, 0, 0.25);
            border-bottom: 1px solid var(--border);
            display: flex;
            flex-direction: column;
            gap: 8px;
        }}
        .tmf-header-title-row {{
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        .tmf-sector-name {{
            font-size: 0.98rem;
            font-weight: 800;
            color: #f8fafc;
            display: flex;
            align-items: center;
            gap: 6px;
        }}
        .tmf-sector-stars {{
            color: #fbbf24;
            font-size: 0.88rem;
        }}
        .tmf-dir-badge {{
            font-size: 0.72rem;
            font-weight: 700;
            padding: 3px 8px;
            border-radius: 6px;
        }}
        .tmf-dir-badge.tmf-up {{
            background: rgba(16, 185, 129, 0.2);
            color: #34d399;
            border: 1px solid rgba(16, 185, 129, 0.4);
        }}
        .tmf-dir-badge.tmf-down {{
            background: rgba(59, 130, 246, 0.2);
            color: #60a5fa;
            border: 1px solid rgba(59, 130, 246, 0.4);
        }}
        .tmf-header-sub-row {{
            display: flex;
            gap: 8px;
            align-items: center;
            font-size: 0.75rem;
            color: #94a3b8;
            flex-wrap: wrap;
        }}
        .tmf-vol-pill {{
            background: rgba(255, 255, 255, 0.06);
            padding: 2px 8px;
            border-radius: 6px;
            border: 1px solid rgba(255, 255, 255, 0.08);
        }}
        .tmf-cnt-pill {{
            background: rgba(255, 255, 255, 0.04);
            padding: 2px 8px;
            border-radius: 6px;
        }}
        .tmf-star-rank {{
            color: #fbbf24;
            font-weight: 700;
        }}
        .tmf-table-scroll {{
            overflow-y: auto;
            scrollbar-width: thin;
            scrollbar-color: rgba(255, 255, 255, 0.2) transparent;
        }}
        .tmf-table-scroll::-webkit-scrollbar {{
            width: 6px;
        }}
        .tmf-table-scroll::-webkit-scrollbar-thumb {{
            background: rgba(255, 255, 255, 0.2);
            border-radius: 3px;
        }}
        .tmf-table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 0.83rem;
        }}
        .tmf-table th {{
            background: rgba(15, 23, 42, 0.85);
            color: #94a3b8;
            font-weight: 600;
            font-size: 0.74rem;
            padding: 8px 12px;
            border-bottom: 1px solid var(--border);
            position: sticky;
            top: 0;
            z-index: 2;
        }}
        .tmf-table td {{
            padding: 8px 12px;
            border-bottom: 1px solid rgba(255, 255, 255, 0.04);
            vertical-align: middle;
        }}
        .tmf-table tr:hover td {{
            background: rgba(255, 255, 255, 0.035);
        }}
        .tmf-td-name {{
            display: flex;
            align-items: center;
            gap: 6px;
            flex-wrap: wrap;
        }}
        .tmf-stock-link {{
            color: #f1f5f9;
            text-decoration: none;
            font-weight: 700;
            transition: color 0.15s;
        }}
        .tmf-stock-link:hover {{
            color: #38bdf8;
            text-decoration: underline;
        }}
        .tmf-stock-stars {{
            color: #fbbf24;
            font-size: 0.8rem;
            margin-left: 2px;
        }}
        .tmf-crown-badge {{
            font-size: 0.65rem;
            background: rgba(245, 158, 11, 0.22);
            color: #fbbf24;
            padding: 1px 5px;
            border-radius: 4px;
            border: 1px solid rgba(245, 158, 11, 0.4);
            font-weight: 800;
        }}
        .tmf-crown-badge-2 {{
            font-size: 0.65rem;
            background: rgba(59, 130, 246, 0.2);
            color: #60a5fa;
            padding: 1px 5px;
            border-radius: 4px;
            border: 1px solid rgba(59, 130, 246, 0.35);
            font-weight: 700;
        }}
        .tmf-crown-badge-3 {{
            font-size: 0.65rem;
            background: rgba(255, 255, 255, 0.08);
            color: #cbd5e1;
            padding: 1px 5px;
            border-radius: 4px;
        }}
        .tmf-td-change {{
            text-align: right;
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.84rem;
        }}
        .tmf-txt-up {{
            color: #f87171 !important;
        }}
        .tmf-txt-down {{
            color: #60a5fa !important;
        }}
        .tmf-txt-even {{
            color: #94a3b8 !important;
        }}
        .tmf-td-vol {{
            text-align: right;
            font-family: 'JetBrains Mono', monospace;
            color: #e2e8f0;
            font-size: 0.78rem;
            font-weight: 600;
        }}
        .tmf-td-note {{
            text-align: center;
        }}
        .tmf-note-pill {{
            font-size: 0.68rem;
            background: rgba(255, 255, 255, 0.08);
            color: #cbd5e1;
            padding: 1px 5px;
            border-radius: 4px;
        }}
        .rec-tab.active {{
            background: linear-gradient(135deg, rgba(245, 158, 11, 0.22), rgba(37, 99, 235, 0.22));
            border-color: #f59e0b;
            border-top: 3px solid #fbbf24;
            color: #ffffff;
            transform: translateY(-2px);
            box-shadow: 0 6px 20px rgba(245, 158, 11, 0.32);
        }}
        .rec-tab.active .rec-tab-title {{
            color: #ffffff;
            text-shadow: 0 0 10px rgba(251, 191, 36, 0.35);
        }}
        [data-theme="light"] .rec-tab {{
            background: #ffffff;
            border-color: rgba(0, 0, 0, 0.12);
            box-shadow: 0 2px 8px rgba(0, 0, 0, 0.05);
        }}
        [data-theme="light"] .rec-tab-title {{
            color: #0f172a;
        }}
        [data-theme="light"] .rec-tab.active {{
            background: linear-gradient(135deg, rgba(245, 158, 11, 0.14), rgba(37, 99, 235, 0.12));
            border-color: #d97706;
        }}
        .rec-tag-pill {{
            font-size: 0.77rem;
            font-weight: 700;
            padding: 4px 10px;
            border-radius: 999px;
            background: rgba(245, 158, 11, 0.22);
            color: #fbbf24;
            border: 1px solid rgba(245, 158, 11, 0.42);
            white-space: nowrap;
        }}
        .pill-emerald {{
            background: rgba(16, 185, 129, 0.22);
            color: #34d399;
            border-color: rgba(16, 185, 129, 0.45);
        }}
        .pill-purple {{
            background: rgba(139, 92, 246, 0.2);
            color: #c084fc;
            border-color: rgba(139, 92, 246, 0.35);
        }}
        .pill-red {{
            background: rgba(239, 68, 68, 0.2);
            color: #f87171;
            border-color: rgba(239, 68, 68, 0.35);
        }}
        .ci-num.num-red {{
            color: #ef4444;
        }}
        .criteria-sub-tag.tag-red {{
            background: rgba(239, 68, 68, 0.15);
            color: #f87171;
            border-color: rgba(239, 68, 68, 0.3);
        }}
        .rec-strategy-banner {{
            border-radius: 12px;
            padding: 12px 16px;
            font-size: 0.85rem;
            line-height: 1.5;
            margin-bottom: 16px;
        }}
        .banner-orange {{
            background: rgba(245, 158, 11, 0.08);
            border: 1px solid rgba(245, 158, 11, 0.25);
            color: #fde68a;
        }}
        .banner-purple {{
            background: rgba(139, 92, 246, 0.08);
            border: 1px solid rgba(139, 92, 246, 0.25);
            color: #e9d5ff;
        }}
        .banner-red {{
            background: rgba(239, 68, 68, 0.08);
            border: 1px solid rgba(239, 68, 68, 0.25);
            color: #fca5a5;
        }}
        .pill-blue {{
            background: rgba(59, 130, 246, 0.2);
            color: #60a5fa;
            border-color: rgba(59, 130, 246, 0.35);
        }}
        .banner-blue {{
            background: rgba(59, 130, 246, 0.08);
            border: 1px solid rgba(59, 130, 246, 0.25);
            color: #93c5fd;
        }}
        .pill-cyan {{
            background: rgba(6, 182, 212, 0.2);
            color: #22d3ee;
            border-color: rgba(6, 182, 212, 0.38);
        }}
        .banner-cyan {{
            background: rgba(6, 182, 212, 0.08);
            border: 1px solid rgba(6, 182, 212, 0.28);
            color: #a5f3fc;
        }}
        .num-cyan {{
            background: rgba(6, 182, 212, 0.22);
            color: #22d3ee;
            border-color: rgba(6, 182, 212, 0.4);
        }}
        .tag-cyan {{
            background: rgba(6, 182, 212, 0.16);
            color: #67e8f9;
            border-color: rgba(6, 182, 212, 0.35);
        }}
        .rec-sector-badge {{
            font-size: 0.74rem;
            color: #a78bfa;
            font-weight: 700;
            margin-left: 4px;
        }}
        .rec-cat-box, .rec-cat-card {{
            font-size: 0.84rem;
            color: #f0f9ff;
            background: linear-gradient(135deg, rgba(30, 58, 138, 0.28), rgba(15, 23, 42, 0.75));
            border: 1px solid rgba(56, 189, 248, 0.35);
            border-left: 3px solid #38bdf8;
            border-radius: 10px;
            padding: 10px 12px;
            margin: 10px 0;
            line-height: 1.5;
            word-break: keep-all;
        }}
        .cat-card-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 6px;
            margin-bottom: 6px;
        }}
        .cat-badge-group {{
            display: flex;
            align-items: center;
            gap: 6px;
        }}
        .cat-label {{
            font-size: 0.74rem;
            font-weight: 800;
            color: #38bdf8;
            background: rgba(56, 189, 248, 0.15);
            border: 1px solid rgba(56, 189, 248, 0.3);
            border-radius: 4px;
            padding: 2px 6px;
            white-space: nowrap;
        }}
        .cat-source {{
            font-size: 0.72rem;
            font-weight: 600;
            color: #94a3b8;
            background: rgba(148, 163, 184, 0.12);
            border-radius: 4px;
            padding: 2px 6px;
        }}
        .cat-link-btn {{
            font-size: 0.73rem;
            font-weight: 700;
            color: #38bdf8;
            text-decoration: none;
            padding: 2px 8px;
            background: rgba(56, 189, 248, 0.1);
            border: 1px solid rgba(56, 189, 248, 0.35);
            border-radius: 6px;
            transition: all 0.2s;
        }}
        .cat-link-btn:hover {{
            background: rgba(56, 189, 248, 0.25);
            color: #ffffff;
            border-color: #38bdf8;
        }}
        .cat-headline {{
            font-size: 0.86rem;
            font-weight: 700;
            line-height: 1.45;
            margin-bottom: 4px;
        }}
        .cat-headline a {{
            color: #f1f5f9;
            text-decoration: none;
            transition: color 0.15s;
        }}
        .cat-headline a:hover {{
            color: #38bdf8;
            text-decoration: underline;
        }}
        .cat-body-snippet {{
            font-size: 0.76rem;
            color: #94a3b8;
            line-height: 1.4;
        }}
        .cat-text {{
            color: #e2e8f0;
            font-weight: 500;
        }}
        .hist-cat-link {{
            color: #38bdf8;
            text-decoration: none;
            font-weight: 600;
        }}
        .hist-cat-link:hover {{
            text-decoration: underline;
        }}
        .hist-cat-src {{
            color: #94a3b8;
            font-size: 0.75rem;
        }}
        .rec-sr-box {{
            font-size: 0.78rem;
            color: #f3f4f6;
            background: rgba(16, 185, 129, 0.05);
            border: 1px solid rgba(16, 185, 129, 0.22);
            border-radius: 8px;
            padding: 8px 10px;
            margin: 8px 0;
            line-height: 1.45;
        }}
        .sr-status-line {{
            color: #f9fafb;
            margin-bottom: 5px;
        }}
        .sr-badge {{
            font-weight: 700;
            color: #34d399;
        }}
        .sr-price-line {{
            display: flex;
            flex-wrap: wrap;
            gap: 6px;
        }}
        .sr-pill {{
            font-size: 0.72rem;
            padding: 2px 7px;
            border-radius: 5px;
        }}
        .sr-pill.pill-green {{
            background: rgba(16, 185, 129, 0.15);
            color: #34d399;
            border: 1px solid rgba(16, 185, 129, 0.3);
        }}
        .sr-pill.pill-gold {{
            background: rgba(245, 158, 11, 0.15);
            color: #fbbf24;
            border: 1px solid rgba(245, 158, 11, 0.3);
        }}
        .rec-bottom-action {{
            margin-top: 10px;
            margin-bottom: 8px;
        }}
        .rec-chart-link {{
            display: inline-block;
            font-size: 0.78rem;
            font-weight: 700;
            color: #38bdf8;
            text-decoration: none;
            background: rgba(56, 189, 248, 0.1);
            border: 1px solid rgba(56, 189, 248, 0.25);
            border-radius: 8px;
            padding: 6px 12px;
            transition: all 0.2s;
        }}
        .rec-chart-link:hover {{
            background: rgba(56, 189, 248, 0.2);
            border-color: #38bdf8;
            color: #ffffff;
        }}
        /* 트랙 레코드 30일 히스토리 */
        .track-summary-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
            gap: 14px;
            margin-bottom: 20px;
        }}
        .track-stat-card {{
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 14px;
            padding: 16px 20px;
        }}
        .track-stat-card.stat-winrate {{
            background: linear-gradient(135deg, rgba(16, 185, 129, 0.14), rgba(17, 24, 39, 0.95));
            border-color: rgba(16, 185, 129, 0.35);
        }}
        .track-stat-card.stat-rr {{
            background: linear-gradient(135deg, rgba(245, 158, 11, 0.14), rgba(17, 24, 39, 0.95));
            border-color: rgba(245, 158, 11, 0.35);
        }}
        .track-stat-card.stat-cum {{
            background: linear-gradient(135deg, rgba(59, 130, 246, 0.14), rgba(17, 24, 39, 0.95));
            border-color: rgba(59, 130, 246, 0.35);
        }}
        .stat-label {{
            font-size: 0.82rem;
            color: var(--text-sub);
            font-weight: 600;
            margin-bottom: 6px;
        }}
        .stat-value {{
            font-size: 1.6rem;
            font-weight: 800;
            color: #ffffff;
            margin-bottom: 4px;
        }}
        .stat-winrate .stat-value {{
            color: #34d399;
        }}
        .stat-rr .stat-value {{
            color: #fbbf24;
        }}
        .stat-cum .stat-value {{
            color: #60a5fa;
        }}
        .stat-swing-winrate .stat-value {{
            color: #c084fc;
        }}
        .stat-swing-rr .stat-value {{
            color: #fbbf24;
        }}
        .stat-swing-cum .stat-value {{
            color: #34d399;
        }}
        .stat-swing-period .stat-value {{
            color: #818cf8;
        }}
        .stat-sub {{
            font-size: 0.74rem;
            color: #9ca3af;
        }}
        .history-timeline {{
            display: flex;
            flex-direction: column;
            gap: 16px;
        }}
        .history-day-card {{
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 14px;
            padding: 18px;
        }}
        .history-day-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid rgba(255, 255, 255, 0.08);
            padding-bottom: 12px;
            margin-bottom: 14px;
        }}
        .day-title {{
            font-size: 0.95rem;
            color: #f9fafb;
        }}
        .hist-badge {{
            font-size: 0.75rem;
            font-weight: 700;
            padding: 3px 8px;
            border-radius: 6px;
        }}
        .badge-done {{
            background: rgba(16, 185, 129, 0.18);
            color: #34d399;
            border: 1px solid rgba(16, 185, 129, 0.3);
        }}
        .badge-wait {{
            background: rgba(245, 158, 11, 0.18);
            color: #fbbf24;
            border: 1px solid rgba(245, 158, 11, 0.3);
        }}
        .history-day-body {{
            display: flex;
            flex-direction: column;
            gap: 10px;
        }}
        .hist-item {{
            background: rgba(255, 255, 255, 0.02);
            border: 1px solid rgba(255, 255, 255, 0.05);
            border-radius: 10px;
            padding: 12px 14px;
        }}
        .hist-item-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 8px;
        }}
        .hist-name-box a {{
            color: #ffffff;
            font-size: 0.95rem;
            text-decoration: none;
        }}
        .hist-name-box a:hover {{
            color: #60a5fa;
            text-decoration: underline;
        }}
        .hist-code {{
            font-size: 0.76rem;
            color: #9ca3af;
            font-family: 'JetBrains Mono', monospace;
        }}
        .hist-sector {{
            font-size: 0.75rem;
            color: #a78bfa;
            margin-left: 6px;
            font-weight: 700;
        }}
        .hist-marcap {{
            font-size: 0.72rem;
            color: #93c5fd;
            background: rgba(59, 130, 246, 0.12);
            border: 1px solid rgba(59, 130, 246, 0.25);
            padding: 1px 6px;
            border-radius: 4px;
            font-weight: 600;
            margin-left: 6px;
        }}
        .hist-result {{
            font-size: 0.85rem;
            color: #d1d5db;
        }}
        .res-badge {{
            font-size: 0.74rem;
            font-weight: 700;
            padding: 2px 7px;
            border-radius: 5px;
            margin-left: 6px;
        }}
        .res-badge.win {{
            background: rgba(16, 185, 129, 0.2);
            color: #34d399;
            border: 1px solid rgba(16, 185, 129, 0.35);
        }}
        .res-badge.even {{
            background: rgba(59, 130, 246, 0.2);
            color: #60a5fa;
            border: 1px solid rgba(59, 130, 246, 0.35);
        }}
        .res-badge.loss {{
            background: rgba(239, 68, 68, 0.2);
            color: #f87171;
            border: 1px solid rgba(239, 68, 68, 0.35);
        }}
        .res-badge.win-gold {{
            background: rgba(245, 158, 11, 0.2);
            color: #fbbf24;
            border: 1px solid rgba(245, 158, 11, 0.4);
        }}
        .res-badge.wait {{
            background: rgba(156, 163, 175, 0.15);
            color: #d1d5db;
            border: 1px solid rgba(156, 163, 175, 0.3);
        }}
        .hist-cat {{
            font-size: 0.78rem;
            color: #9ca3af;
            margin-top: 6px;
            padding-top: 6px;
            border-top: 1px dashed rgba(255, 255, 255, 0.06);
        }}
        .rec-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
            gap: 16px;
            margin-bottom: 28px;
        }}
        .rec-card {{
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 14px;
            padding: 18px;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
            transition: all 0.25s;
            position: relative;
        }}
        .rec-card:hover {{
            transform: translateY(-3px);
            box-shadow: 0 10px 28px rgba(0, 0, 0, 0.4);
        }}
        .rec-card.theme-closing {{
            border-top: 3px solid #f59e0b;
        }}
        .rec-card.theme-swing {{
            border-top: 3px solid #8b5cf6;
        }}
        .rec-card.theme-breakout {{
            border-top: 3px solid #ef4444;
        }}
        .rec-card.theme-condition {{
            border-top: 3px solid #06b6d4;
        }}
        .rec-card-top {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 12px;
        }}
        .rec-stock-title a {{
            font-size: 1.15rem;
            font-weight: 800;
            color: #ffffff !important;
            text-decoration: none;
            display: inline-flex;
            align-items: center;
            gap: 6px;
        }}
        .rec-stock-title a:hover {{
            text-decoration: underline;
        }}
        .rec-code {{
            font-size: 0.8rem;
            color: #9ca3af;
            font-family: 'JetBrains Mono', monospace;
            font-weight: 600;
        }}
        .rec-market-badge {{
            font-size: 0.7rem;
            padding: 2px 6px;
            border-radius: 4px;
            background: rgba(255, 255, 255, 0.08);
            color: #d1d5db;
            margin-left: 4px;
        }}
        .rec-marcap-badge {{
            font-size: 0.7rem;
            padding: 2px 6px;
            border-radius: 4px;
            background: rgba(59, 130, 246, 0.12);
            color: #93c5fd;
            border: 1px solid rgba(59, 130, 246, 0.25);
            margin-left: 4px;
            font-weight: 600;
        }}
        .rec-score-badge {{
            font-size: 0.74rem;
            font-weight: 700;
            padding: 3px 9px;
            border-radius: 999px;
            background: rgba(16, 185, 129, 0.15);
            color: #34d399;
            border: 1px solid rgba(16, 185, 129, 0.35);
        }}
        .rec-price-row {{
            display: flex;
            justify-content: space-between;
            align-items: baseline;
            margin-bottom: 14px;
            padding-bottom: 10px;
            border-bottom: 1px solid rgba(255, 255, 255, 0.06);
        }}
        .rec-label {{
            font-size: 0.78rem;
            color: var(--text-sub);
            margin-right: 6px;
        }}
        .rec-price {{
            font-size: 1.35rem;
            font-weight: 800;
            font-family: 'JetBrains Mono', monospace;
            color: #ffffff;
        }}
        .rec-change-box {{
            font-size: 0.88rem;
            font-weight: 700;
            font-family: 'JetBrains Mono', monospace;
        }}
        .rec-target-box {{
            display: grid;
            grid-template-columns: 1fr 1fr 1fr;
            gap: 6px;
            background: rgba(0, 0, 0, 0.35);
            border: 1px solid rgba(255, 255, 255, 0.06);
            border-radius: 10px;
            padding: 10px;
            margin-bottom: 12px;
            text-align: center;
        }}
        .target-col .t-label {{
            font-size: 0.68rem;
            color: #9ca3af;
            margin-bottom: 4px;
        }}
        .target-col .t-val {{
            font-size: 0.88rem;
            font-weight: 700;
            font-family: 'JetBrains Mono', monospace;
        }}
        .col-t1 .t-val {{ color: #f87171; }}
        .col-t2 .t-val {{ color: #ef4444; }}
        .col-sl .t-val {{ color: #60a5fa; }}
        .col-t3 .t-val {{ color: #fbbf24; }}
        .rec-target-box.four-col {{ grid-template-columns: repeat(4, 1fr); }}
        @media (max-width: 480px) {{
            .rec-target-box.four-col {{ grid-template-columns: repeat(2, 1fr); }}
        }}
        .rec-date-badge {{
            font-size: 0.76rem;
            color: #c4b5fd;
            background: rgba(139, 92, 246, 0.12);
            border: 1px solid rgba(139, 92, 246, 0.35);
            border-radius: 8px;
            padding: 5px 10px;
            margin: 6px 0 10px;
            line-height: 1.5;
        }}
        .rec-desc-box {{
            background: rgba(0, 0, 0, 0.2);
            border: 1px solid rgba(255, 255, 255, 0.04);
            border-radius: 8px;
            padding: 10px;
            font-size: 0.8rem;
            line-height: 1.5;
            margin-bottom: 10px;
        }}
        .rec-desc-title {{
            color: #9ca3af;
            font-weight: 600;
            font-size: 0.74rem;
            margin-bottom: 3px;
        }}
        .rec-desc-text {{
            color: #f3f4f6;
            margin-bottom: 6px;
        }}
        .rec-period-tag {{
            font-size: 0.72rem;
            color: #fbbf24;
            font-weight: 600;
        }}
        .rec-tags-row {{
            display: flex;
            gap: 6px;
            flex-wrap: wrap;
        }}
        .rec-tag {{
            font-size: 0.7rem;
            padding: 2px 7px;
            border-radius: 4px;
            background: rgba(255, 255, 255, 0.06);
            color: #9ca3af;
        }}

        /* 가이드 탭 & 박스 */
        .tabs {{
            display: flex;
            gap: 8px;
            flex-wrap: wrap;
            align-items: center;
            padding-bottom: 4px;
            margin-bottom: 14px;
            scrollbar-width: none;
            -ms-overflow-style: none;
        }}
        .tabs::-webkit-scrollbar {{
            display: none;
        }}
        .tab-btn {{
            background: var(--surface);
            border: 1px solid var(--border);
            color: var(--text-sub);
            padding: 10px 16px;
            border-radius: 10px;
            font-size: 0.88rem;
            font-weight: 600;
            cursor: pointer;
            white-space: nowrap;
            transition: all 0.2s;
        }}
        .tab-btn.active {{
            background: #2563eb;
            color: #fff;
            border-color: #3b82f6;
            box-shadow: 0 4px 14px rgba(37,99,235,0.4);
        }}
        .guide-content {{
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 16px;
            padding: 22px;
            line-height: 1.8;
            font-size: 0.95rem;
            white-space: pre-line;
            box-shadow: 0 10px 30px rgba(0,0,0,0.3);
        }}

        /* 공시 카테고리 탭 네비게이션 */
        .disclosure-nav {{
            display: flex;
            gap: 10px;
            flex-wrap: wrap;
            align-items: center;
            padding-bottom: 4px;
            margin-bottom: 20px;
            scrollbar-width: none;
            -ms-overflow-style: none;
        }}
        .disclosure-nav::-webkit-scrollbar {{
            display: none;
        }}
        .disc-tab {{
            background: var(--surface);
            border: 1px solid var(--border);
            color: var(--text-sub);
            padding: 10px 18px;
            border-radius: 12px;
            font-size: 0.9rem;
            font-weight: 600;
            cursor: pointer;
            white-space: nowrap;
            display: flex;
            align-items: center;
            gap: 8px;
            transition: all 0.2s;
        }}
        .disc-tab:hover {{
            border-color: rgba(255,255,255,0.2);
            color: var(--text-main);
        }}
        .disc-tab.active {{
            background: rgba(59, 130, 246, 0.18);
            border-color: #3b82f6;
            color: #ffffff;
            box-shadow: 0 4px 14px rgba(59, 130, 246, 0.25);
        }}
        .tab-count {{
            display: inline-block;
            font-size: 0.75rem;
            padding: 2px 7px;
            border-radius: 999px;
            background: rgba(255, 255, 255, 0.08);
            color: var(--text-sub);
            font-family: 'JetBrains Mono', monospace;
        }}
        .disc-tab.active .tab-count {{
            background: #3b82f6;
            color: #fff;
        }}
        .count-green {{ background: rgba(16, 185, 129, 0.2); color: #34d399; }}
        .count-gold {{ background: rgba(245, 158, 11, 0.2); color: #fbbf24; }}
        .count-purple {{ background: rgba(139, 92, 246, 0.2); color: #a78bfa; }}

        /* 카테고리 그룹 컨테이너 */
        .category-group {{
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 16px;
            padding: 20px;
            margin-bottom: 24px;
            transition: all 0.3s;
        }}
        .category-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 8px;
            padding-bottom: 14px;
            margin-bottom: 16px;
            border-bottom: 1px solid rgba(255, 255, 255, 0.06);
        }}
        .cat-title {{
            font-size: 1.1rem;
            font-weight: 700;
            display: flex;
            align-items: center;
            gap: 8px;
        }}
        .cat-badge {{
            font-size: 0.78rem;
            font-weight: 600;
            padding: 4px 10px;
            border-radius: 999px;
        }}
        .header-green .cat-title {{ color: #34d399; }}
        .header-green .cat-badge {{ background: rgba(16, 185, 129, 0.15); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.3); }}
        .header-gold .cat-title {{ color: #fbbf24; }}
        .header-gold .cat-badge {{ background: rgba(245, 158, 11, 0.15); color: #fbbf24; border: 1px solid rgba(245, 158, 11, 0.3); }}
        .header-purple .cat-title {{ color: #c084fc; }}
        .header-purple .cat-badge {{ background: rgba(139, 92, 246, 0.15); color: #c084fc; border: 1px solid rgba(139, 92, 246, 0.3); }}

        /* 공시 카드 스타일 */
        .disclosure-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
            gap: 14px;
        }}
        .disclosure-card {{
            background: rgba(17, 24, 39, 0.7);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 16px;
            transition: transform 0.2s, border-color 0.2s, box-shadow 0.2s;
            position: relative;
        }}
        .disclosure-card:hover {{
            transform: translateY(-2px);
            border-color: rgba(255, 255, 255, 0.2);
            box-shadow: 0 8px 24px rgba(0, 0, 0, 0.3);
        }}
        .disclosure-card.type-earnings {{
            border-left: 4px solid #10b981;
        }}
        .disclosure-card.type-burn {{
            border-left: 4px solid #ef4444;
            background: linear-gradient(135deg, rgba(239, 68, 68, 0.08), rgba(17, 24, 39, 0.95));
        }}
        .disclosure-card.type-buyback {{
            border-left: 4px solid #f59e0b;
        }}
        .disclosure-card.type-ir {{
            border-left: 4px solid #8b5cf6;
        }}
        .disclosure-card.is-burn {{
            border-color: rgba(239, 68, 68, 0.5);
            box-shadow: 0 4px 20px rgba(239, 68, 68, 0.15);
        }}
        .disclosure-card.is-watchlist {{
            background: linear-gradient(135deg, rgba(245, 158, 11, 0.06), rgba(17, 24, 39, 0.95));
            border-color: rgba(245, 158, 11, 0.35);
        }}
        .card-top-row {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 10px;
        }}
        .watch-tag {{
            font-size: 0.74rem;
            font-weight: 700;
            color: #fbbf24;
            background: rgba(245, 158, 11, 0.15);
            padding: 3px 8px;
            border-radius: 6px;
            border: 1px solid rgba(245, 158, 11, 0.35);
        }}
        .watch-tag.tag-burn {{
            color: #fca5a5;
            background: rgba(239, 68, 68, 0.22);
            border-color: rgba(239, 68, 68, 0.5);
            box-shadow: 0 0 10px rgba(239, 68, 68, 0.2);
        }}
        .watch-tag.tag-surprise {{
            color: #34d399;
            background: rgba(16, 185, 129, 0.18);
            border-color: rgba(16, 185, 129, 0.4);
        }}
        .watch-tag.tag-turnaround {{
            color: #60a5fa;
            background: rgba(59, 130, 246, 0.18);
            border-color: rgba(59, 130, 246, 0.4);
        }}
        .watch-tag.tag-growth {{
            color: #a78bfa;
            background: rgba(139, 92, 246, 0.18);
            border-color: rgba(139, 92, 246, 0.4);
        }}
        .watch-tag.tag-buyback {{
            color: #fbbf24;
            background: rgba(245, 158, 11, 0.18);
            border-color: rgba(245, 158, 11, 0.4);
        }}
        .badge-fire {{
            background: rgba(239, 68, 68, 0.2);
            color: #f87171;
            border: 1px solid rgba(239, 68, 68, 0.4);
        }}
        .badge {{
            font-size: 0.75rem;
            font-weight: 700;
            padding: 3px 8px;
            border-radius: 6px;
        }}
        .badge-green {{ background: rgba(16,185,129,0.2); color: #34d399; }}
        .badge-gold {{ background: rgba(245,158,11,0.2); color: #fbbf24; }}
        .badge-purple {{ background: rgba(139,92,246,0.2); color: #a78bfa; }}
        .card-main-title {{
            font-size: 0.98rem;
            font-weight: 700;
            color: #ffffff !important;
            margin-bottom: 8px;
            line-height: 1.45;
        }}
        .card-main-title a,
        .card-main-title a:link,
        .card-main-title a:visited,
        .card-main-title a:hover,
        .card-main-title a:active,
        .card-main-title b {{
            color: #ffffff !important;
            text-decoration: underline;
            text-decoration-color: rgba(255, 255, 255, 0.4);
            font-weight: 700;
        }}
        .card-main-title a:hover {{
            color: #ffffff !important;
            text-decoration-color: #ffffff;
        }}
        .card-details {{
            font-size: 0.85rem;
            color: #f3f4f6 !important;
            line-height: 1.65;
            background: rgba(0, 0, 0, 0.35);
            padding: 10px 12px;
            border-radius: 8px;
            border: 1px solid rgba(255, 255, 255, 0.08);
        }}
        .card-details a,
        .card-details a:link,
        .card-details a:visited,
        .card-details a:hover {{
            color: #ffffff !important;
            text-decoration: underline;
        }}
        .card-details b {{
            color: #ffffff !important;
        }}
        .empty-card {{
            padding: 30px;
            text-align: center;
            color: var(--text-sub);
            background: rgba(0, 0, 0, 0.2);
            border-radius: 12px;
            border: 1px dashed rgba(255, 255, 255, 0.08);
            grid-column: 1 / -1;
            font-size: 0.88rem;
        }}

        footer {{
            margin-top: 48px;
            padding: 24px 0;
            text-align: center;
            border-top: 1px solid var(--border);
            color: var(--text-sub);
            font-size: 0.82rem;
        }}
    </style>
</head>
<body>
    <header>
        <div class="logo-area">
            <h1>🧭 비니stock 트레이딩 대시보드</h1>
            <div class="quick-etf-bar">
                <span class="quick-label">⚡ 글로벌 퀵:</span>
                <a href="https://m.stock.naver.com/worldstock/index/.IXIC" target="_blank" rel="noopener noreferrer" class="quick-tag">나스닥</a>
                <a href="https://m.stock.naver.com/worldstock/etf/QQQ" target="_blank" rel="noopener noreferrer" class="quick-tag">QQQ</a>
                <a href="https://m.stock.naver.com/worldstock/etf/SPY" target="_blank" rel="noopener noreferrer" class="quick-tag">SPY</a>
                <a href="https://m.stock.naver.com/worldstock/etf/SOXX" target="_blank" rel="noopener noreferrer" class="quick-tag">SOXX</a>
                <a href="https://m.stock.naver.com/worldstock/stock/NVDA.O/total" target="_blank" rel="noopener noreferrer" class="quick-tag">NVDA</a>
                <a href="javascript:void(0)" onclick="switchRecTrack('flow', document.querySelector('.rec-tab.tab-rose')); document.getElementById('rec-flow-container').scrollIntoView({{behavior: 'smooth'}});" class="quick-tag" style="background: rgba(244,63,94,0.22); color: #fb7185; border-color: rgba(244,63,94,0.45); font-weight: 700;">💸 오늘 돈 몰리는 곳</a>
            </div>
        </div>
        <div class="header-right-controls">
            <button id="refresh-now-btn" class="toolbar-btn refresh-btn" onclick="refreshDashboardNow()" title="최신 데이터 실시간 새로고침 (캐시 우회)">
                🔄 <span id="refresh-btn-text">실시간 새로고침</span>
            </button>
            <button id="cloud-modal-btn" class="toolbar-btn cloud-btn" onclick="openCloudModal()" title="외부/스마트폰에서 깃허브 클라우드 즉시 재분석 실행">
                ⚡ <span>클라우드 갱신</span>
            </button>
            <button id="theme-toggle-btn" class="toolbar-btn" onclick="toggleTheme()" title="다크/라이트 테마 변경">
                🌓 <span id="theme-btn-text">라이트모드</span>
            </button>
            <div class="time-badge">
                <span class="live-dot"></span>{now_str}
            </div>
        </div>
    </header>

    <!-- 실시간 클라우드 재분석 모달 -->
    <div id="cloud-modal" class="modal-overlay" style="display:none;" onclick="if(event.target===this)closeCloudModal()">
        <div class="modal-content">
            <div class="modal-header">
                <h3>⚡ 실시간 클라우드 재분석 & 배포</h3>
                <button class="modal-close" onclick="closeCloudModal()">✕</button>
            </div>
            <div class="modal-body">
                <div class="modal-desc">
                    스마트폰(길거리)이나 외부 PC에서도 버튼 하나로 깃허브 클라우드를 깨워 <b>실시간 나스닥 선물, 반도체, 환율, 수급을 즉시 재수집하고 대시보드를 새로고침</b>할 수 있습니다.
                </div>
                
                <div class="cloud-action-card">
                    <div class="cac-title">🚀 방법 1. 원클릭 깃허브 액션 즉시 실행 (가장 추천)</div>
                    <div class="cac-desc">모바일 브라우저에서 깃허브 액션 페이지로 바로 이동하여 [Run workflow] 버튼을 누릅니다. (약 1분 후 최신 웹 자동 배포)</div>
                    <a href="https://github.com/parkseungbin1/binistock/actions/workflows/deploy-web.yml" target="_blank" rel="noopener noreferrer" class="cac-btn primary">
                        ⚡ 깃허브 실행창 바로가기 (Run workflow)
                    </a>
                </div>

                <div class="cloud-action-card">
                    <div class="cac-title">🔑 방법 2. 스마트폰 원터치 직접 실행 (GitHub 토큰 1회 저장)</div>
                    <div class="cac-desc">GitHub 토큰(PAT)을 내 폰에 1회만 저장해두면, 위 페이지로 이동할 필요도 없이 이 화면에서 1초 만에 클라우드 빌드를 시작합니다.</div>
                    <div class="token-input-row">
                        <input type="password" id="gh-token-input" placeholder="ghp_... (GitHub Personal Access Token)" class="token-input">
                        <button onclick="saveAndTriggerWorkflow()" class="cac-btn green">🚀 즉시 실행</button>
                    </div>
                    <div id="token-status" class="token-status"></div>
                </div>

                <div class="cloud-schedule-box">
                    <div class="csb-title">⏰ BiniStock 실시간 자동 배포 스케줄 (텔레그램 8대 알림 100% 동기화)</div>
                    <ul>
                        <li>🌅 <b>07:00 KST</b> : 모닝 시황 브리핑 & 주간 캘린더</li>
                        <li>⚡ <b>07:35 KST</b> : NXT 개장 전 1차 시초가 매도 가이드</li>
                        <li>📑 <b>08:10 KST</b> : DART 실적 & 핵심 공시</li>
                        <li>🎯 <b>08:35 KST</b> : 정규장 개장 전 최종 시초가 매도 가이드</li>
                        <li>☀️ <b>13:00 KST</b> : 오후장 개시 시황 & 수급 중간점검</li>
                        <li>🎯 <b>14:00 KST</b> : 종가베팅 1시간 전 사전 레이더 & 리스크 점검</li>
                        <li>🔥 <b>15:10 KST</b> : 정규장 15:10 공식 종가베팅 골든타임</li>
                        <li>🌙 <b>19:40 KST</b> : NXT 야간 최종 종가베팅 가이드</li>
                    </ul>
                    <div class="csb-sub">※ 텔레그램 8대 알림 발송과 동시에 웹 대시보드가 실시간으로 자동 갱신됩니다.</div>
                </div>
            </div>
        </div>
    </div>

    <!-- 0. AI 실시간 복합 시장 리스크 스코어 배너 -->
    <div class="risk-banner-card {risk_badge_class}">
        <div class="risk-left">
            <div class="risk-title-row">
                <span class="risk-icon-pill">🛡️ AI 실시간 시장 리스크 스코어</span>
                <span class="risk-status-badge">{risk_grade}</span>
                <button class="risk-quick-refresh-btn" onclick="refreshDashboardNow()" title="실시간 최신 데이터 동기화">🔄 새로고침</button>
            </div>
            <div class="risk-desc-text">{risk_desc}</div>
        </div>
        <div class="risk-right">
            <div class="risk-score-display">
                <span class="risk-score-num" style="color: {risk_color};">{ai_risk_score}</span>
                <span class="risk-score-unit">/ 100점</span>
            </div>
            <div class="risk-meter-bar-container">
                <div class="risk-meter-bar-fill" style="width: {ai_risk_score}%; background: {risk_color};"></div>
            </div>
        </div>
    </div>

    <!-- 1. 핵심 지표 그리드 -->
    <div class="grid-indicators">
        <div class="metric-card">
            <div class="metric-top-row">
                <span class="metric-label">🇺🇸 E-mini 나스닥100 선물</span>
                {fut_impact_badge}
            </div>
            <div class="metric-main-row">
                <div class="metric-value">{fut_display}</div>
                <a href="https://kr.tradingview.com/symbols/CME_MINI-NQ1!/" target="_blank" rel="noopener noreferrer" class="live-quote-link" title="트레이딩뷰 실시간 CME 나스닥100 선물 틱 차트 및 호가 보기">🔴 실시간 호가 ↗</a>
            </div>
            <div class="metric-sub">{fut_badge} (CME 실시간 수집)</div>
            <div class="metric-desc">
                <div class="metric-desc-title">💡 시장 영향 & 실전 의미</div>
                <div class="metric-desc-text">{fut_impact_desc}</div>
            </div>
        </div>

        <div class="metric-card">
            <div class="metric-top-row">
                <span class="metric-label">💻 필라델피아 반도체</span>
                {sox_impact_badge}
            </div>
            <div class="metric-main-row">
                <div class="metric-value">{sox_display}</div>
                <a href="https://m.stock.naver.com/worldstock/index/.SOX" target="_blank" rel="noopener noreferrer" class="live-quote-link" title="네이버 증권 실시간 반도체 지수 보기">🔴 실시간 ↗</a>
            </div>
            <div class="metric-sub">{sox_badge}</div>
            <div class="metric-desc">
                <div class="metric-desc-title">💡 시장 영향 & 실전 의미</div>
                <div class="metric-desc-text">{sox_impact_desc}</div>
            </div>
        </div>

        <div class="metric-card">
            <div class="metric-top-row">
                <span class="metric-label">🇰🇷 코스피 & 수급</span>
                {kp_impact_badge}
            </div>
            <div class="metric-main-row">
                <div class="metric-value">{kp_display}</div>
            </div>
            <div class="metric-sub">{kp_badge} | 외인 {kp_for}억 · 기관 {kp_inst}억 (윗꼬리 {kp_pb:.2f}%p)</div>
            <div class="metric-desc">
                <div class="metric-desc-title">💡 시장 영향 & 실전 의미</div>
                <div class="metric-desc-text">{kp_impact_desc}</div>
            </div>
        </div>

        <div class="metric-card">
            <div class="metric-top-row">
                <span class="metric-label">🇰🇷 코스닥 & 수급</span>
                {kd_impact_badge}
            </div>
            <div class="metric-main-row">
                <div class="metric-value">{kd_display}</div>
            </div>
            <div class="metric-sub">{kd_badge} | 외인 {kd_for}억 · 기관 {kd_inst}억 (상승종목 {breadth_val:.0f}%)</div>
            <div class="metric-desc">
                <div class="metric-desc-title">💡 시장 영향 & 실전 의미</div>
                <div class="metric-desc-text">{kd_impact_desc}</div>
            </div>
        </div>

        <div class="metric-card">
            <div class="metric-top-row">
                <span class="metric-label">💱 원/달러 환율</span>
                {fx_impact_badge}
            </div>
            <div class="metric-main-row">
                <div class="metric-value">{fx_display}</div>
                <a href="https://m.stock.naver.com/marketindex/exchange/FX_USDKRW" target="_blank" rel="noopener noreferrer" class="live-quote-link" title="네이버 증권 실시간 환율 보기">🔴 실시간 ↗</a>
            </div>
            <div class="metric-sub">{fx_badge}</div>
            <div class="metric-desc">
                <div class="metric-desc-title">💡 시장 영향 & 실전 의미</div>
                <div class="metric-desc-text">{fx_impact_desc}</div>
            </div>
        </div>

        <div class="metric-card">
            <div class="metric-top-row">
                <span class="metric-label">🧭 CNN 공포/탐욕</span>
                {cnn_impact_badge}
            </div>
            <div class="metric-main-row">
                <div class="metric-value">{cnn_score:.0f}점</div>
            </div>
            <div class="metric-sub">{cnn_rating.upper()} (월가 투자심리)</div>
            <div class="metric-desc">
                <div class="metric-desc-title">💡 시장 영향 & 실전 의미</div>
                <div class="metric-desc-text">{cnn_impact_desc}</div>
            </div>
        </div>

        <div class="metric-card">
            <div class="metric-top-row">
                <span class="metric-label">🌪️ VIX 변동성 지수</span>
                {vix_impact_badge}
            </div>
            <div class="metric-main-row">
                <div class="metric-value">{vix_display}</div>
            </div>
            <div class="metric-sub">{vix_badge} (월가 공포)</div>
            <div class="metric-desc">
                <div class="metric-desc-title">💡 시장 영향 & 실전 의미</div>
                <div class="metric-desc-text">{vix_impact_desc}</div>
            </div>
        </div>

        <div class="metric-card">
            <div class="metric-top-row">
                <span class="metric-label">📈 미국 10년물 국채금리</span>
                {us10y_impact_badge}
            </div>
            <div class="metric-main-row">
                <div class="metric-value">{us10y_display}</div>
            </div>
            <div class="metric-sub">{us10y_badge} (글로벌 긴축)</div>
            <div class="metric-desc">
                <div class="metric-desc-title">💡 시장 영향 & 실전 의미</div>
                <div class="metric-desc-text">{us10y_impact_desc}</div>
            </div>
        </div>
    </div>

    <!-- 2. AI 실전 추천 레이더 (라씨 벤치마킹) -->
    <div class="section-title">
        <span>🎯 AI 실전 추천 레이더 (라씨 벤치마킹)</span>
    </div>
    <div style="font-size: 0.85rem; color: #9ca3af; margin-top: -8px; margin-bottom: 16px;">
        💡 코스피·코스닥 2,800개 전 종목의 수급, 거래대금, 20일선 눌림목을 분석하여 <b>[당일 종가베팅]</b>과 <b>[2~5일 스윙]</b> 최우량주를 엄선합니다.
    </div>

    <!-- 시장 안전도(Market Regime) 레짐 배너 -->
    <div class="rec-market-alert {rec_regime.get('badge_class', 'regime-neutral')}">
        <div class="regime-header">
            <span class="regime-badge">{rec_regime.get('badge', '🔵 시장 환경 분석')}</span>
            <span class="regime-advice">AI 권장 포지션: <b>{rec_regime.get('position_advice', '원칙 분할 매매')}</b></span>
        </div>
        <div class="regime-msg">{rec_regime.get('message', '')}</div>
    </div>

    <!-- [아이디어 5] 오늘의 최강 주도 섹터 TOP 3 (Sector Sympathy 레이더) -->
    <div style="background: var(--surface); border: 1px solid var(--border); border-radius: 14px; padding: 14px 18px; margin-bottom: 16px;">
        <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px; margin-bottom:10px;">
            <span style="font-size:0.92rem; font-weight:800; color:var(--text-main);">🔥 오늘의 최강 주도 섹터 TOP 3 (Sector Sympathy 동조화 레이더)</span>
            <span style="font-size:0.75rem; color:#9ca3af;">💡 단독 상승주보다 자금이 집결된 주도 섹터 1등주 공략 시 승률 극대화 (AI 추천 자동 가산점 부여)</span>
        </div>
        <div style="display:flex; gap:12px; flex-wrap:wrap;">
            {hot_sectors_html}
        </div>
    </div>

    <!-- [아이디어 9] 리스크 스코어 × 하프 켈리(Half-Kelly) 연동 실전 시드머니 & 포지션 사이징 계산기 -->
    <div style="background: linear-gradient(135deg, rgba(30, 58, 138, 0.22), rgba(17, 24, 39, 0.95)); border: 1px solid rgba(59, 130, 246, 0.35); border-left: 4px solid #3b82f6; border-radius: 14px; padding: 16px 20px; margin-bottom: 18px;">
        <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:12px; margin-bottom:12px;">
            <div>
                <div style="font-size:0.96rem; font-weight:800; color:#f9fafb; display:flex; align-items:center; gap:8px; flex-wrap:wrap;">
                    💰 AI 리스크 & 하프 켈리(Half-Kelly) 실전 시드머니 계산기
                    <span style="font-size:0.72rem; background:rgba(59,130,246,0.2); color:#60a5fa; padding:2px 8px; border-radius:999px; border:1px solid rgba(59,130,246,0.4);">전체 종목 카드 실시간 연동</span>
                    <span style="font-size:0.72rem; background:rgba(168,85,247,0.2); color:#c084fc; padding:2px 8px; border-radius:999px; border:1px solid rgba(168,85,247,0.4);">🤖 칼만 필터(Kalman) 적응형 자기보정</span>
                </div>
                <div style="font-size:0.78rem; color:#9ca3af; margin-top:2px;">
                    최근 30일 승률(<b>{kelly_win_rate}%</b>) · 칼만 추정 승률(<b>{kalman_win_rate}%</b>) · 손익비(<b>{kalman_rr}:1</b>) · 모멘텀(<b>{kalman_mom}</b>) · AI 리스크(<b>{ai_risk_score}점</b>) 결합 최적 베팅액 산출
                </div>
            </div>
            <div style="display:flex; align-items:center; gap:8px; background:rgba(0,0,0,0.35); padding:8px 12px; border-radius:10px; border:1px solid rgba(255,255,255,0.1);">
                <label for="seed-money-input" style="font-size:0.82rem; font-weight:700; color:#e5e7eb;">나의 총 운용 시드:</label>
                <input id="seed-money-input" type="number" value="1000" min="10" step="100" oninput="updateKellyCalculator()" style="width:90px; background:#0b0f19; color:#34d399; font-family:'JetBrains Mono',monospace; font-weight:800; font-size:0.95rem; border:1px solid #3b82f6; border-radius:6px; padding:4px 8px; text-align:right;">
                <span style="font-size:0.85rem; font-weight:700; color:#e5e7eb;">만원</span>
            </div>
        </div>
        <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(190px, 1fr)); gap:10px; font-size:0.82rem;">
            <div style="background:rgba(0,0,0,0.3); padding:10px 12px; border-radius:8px; border:1px solid rgba(255,255,255,0.06);">
                <div style="color:#9ca3af; font-size:0.74rem;">🎯 오늘 권장 총 투입 비중 ({recommended_invest_pct}%)</div>
                <div id="kelly-total-invest" style="font-family:'JetBrains Mono',monospace; font-size:1.05rem; font-weight:800; color:#34d399; margin-top:2px;">-</div>
            </div>
            <div style="background:rgba(0,0,0,0.3); padding:10px 12px; border-radius:8px; border:1px solid rgba(255,255,255,0.06);">
                <div style="color:#9ca3af; font-size:0.74rem;">🛡️ 의무 현금 보유액 ({100 - recommended_invest_pct}%)</div>
                <div id="kelly-cash-reserve" style="font-family:'JetBrains Mono',monospace; font-size:1.05rem; font-weight:800; color:#60a5fa; margin-top:2px;">-</div>
            </div>
            <div style="background:rgba(0,0,0,0.3); padding:10px 12px; border-radius:8px; border:1px solid rgba(255,255,255,0.06);">
                <div style="color:#9ca3af; font-size:0.74rem;">⚡ 1종목당 권장 매수액 (3종목 분산)</div>
                <div id="kelly-per-stock" style="font-family:'JetBrains Mono',monospace; font-size:1.05rem; font-weight:800; color:#fbbf24; margin-top:2px;">-</div>
            </div>
            <div style="background:rgba(0,0,0,0.3); padding:10px 12px; border-radius:8px; border:1px solid rgba(255,255,255,0.06);">
                <div style="color:#9ca3af; font-size:0.74rem;">🚨 1종목 손절(-2%) 시 최대 손실액</div>
                <div id="kelly-max-loss" style="font-family:'JetBrains Mono',monospace; font-size:1.05rem; font-weight:800; color:#f87171; margin-top:2px;">-</div>
            </div>
        </div>
    </div>

    <!-- 추천 트랙 선택 탭 -->
    <div class="rec-nav">
        <button class="rec-tab tab-amber active" onclick="switchRecTrack('closing', this)">
            <span class="rec-tab-title">{closing_tab_title}</span>
            <span class="rec-tag-pill">{closing_tab_pill}</span>
        </button>
        <button class="rec-tab tab-purple" onclick="switchRecTrack('swing', this)">
            <span class="rec-tab-title">🌊 2~5일 스윙 추천</span>
            <span class="rec-tag-pill pill-purple">3분할 +3/+5/+9% · 손절 -3%</span>
        </button>
        <button class="rec-tab tab-red" onclick="switchRecTrack('breakout', this)">
            <span class="rec-tab-title">🔥 당일 +15% 돌파 대장주</span>
            <span class="rec-tag-pill pill-red">기준봉·눌림목 포착</span>
        </button>
        <button class="rec-tab tab-cyan" onclick="switchRecTrack('condition', this)">
            <span class="rec-tab-title">🎯 내 조건식 (60일 1000억)</span>
            <span class="rec-tag-pill pill-cyan">{cond_tab_pill}</span>
        </button>
        <button class="rec-tab tab-blue" onclick="switchRecTrack('history', this)">
            <span class="rec-tab-title">📜 1개월 종가베팅 성과</span>
            <span class="rec-tag-pill pill-blue">1달치 승률 자동기록</span>
        </button>
        <button class="rec-tab tab-indigo" onclick="switchRecTrack('swing_history', this)">
            <span class="rec-tab-title">📊 1개월 스윙 성과</span>
            <span class="rec-tag-pill pill-purple">2~5일 추세추적 기록</span>
        </button>
        <button class="rec-tab tab-emerald" onclick="switchRecTrack('playbook', this)">
            <span class="rec-tab-title">📘 실전 200% 활용법</span>
            <span class="rec-tag-pill pill-emerald">★ 10대 천재 매매공식</span>
        </button>
        <button class="rec-tab tab-rose" onclick="switchRecTrack('flow', this)">
            <span class="rec-tab-title">💸 실시간 머니플로우</span>
            <span class="rec-tag-pill" style="background:rgba(244,63,94,0.22); color:#fb7185; border-color:rgba(244,63,94,0.45);">🔥 오늘 돈 몰리는 곳</span>
        </button>
    </div>

    <!-- 시가총액 필터 바 -->
    <div class="marcap-filter-bar">
        <span class="mfilter-label">🏷️ 시가총액 필터:</span>
        <button class="mfilter-btn active" onclick="filterByMarcap('all', this)">전체보기</button>
        <button class="mfilter-btn" onclick="filterByMarcap('large', this)">대형주 (1조원+)</button>
        <button class="mfilter-btn" onclick="filterByMarcap('mid', this)">중형주 (3천억~1조)</button>
        <button class="mfilter-btn" onclick="filterByMarcap('small', this)">스몰캡 (3천억 미만)</button>
    </div>

    <!-- 1) 종가베팅 컨테이너 -->
    <div id="rec-closing-container" class="rec-container">
        <div class="rec-strategy-banner banner-orange">
            <div>
                {closing_banner_html}
            </div>
        </div>

        <!-- 🔍 15:10 종가베팅 4대 선별 기준 설명 박스 -->
        <div class="criteria-card">
            <div class="criteria-head">
                <span>🔍 AI 15:10 종가베팅 4대 엄격 선별 기준 (당일 승률 극대화)</span>
                <span class="criteria-sub-tag">오버나잇 승률 모델</span>
            </div>
            <div class="criteria-grid">
                <div class="criteria-item">
                    <div class="ci-num">01</div>
                    <div class="ci-content">
                        <div class="ci-title">거래대금 최우선 집중 (수백억~1,000억+)</div>
                        <div class="ci-desc">시장의 메이저 자금이 쏠린 최상위 주도주만 선별 (호가창이 얇아 매도 시 손해보는 소형 거래량 종목 원천 배제)</div>
                    </div>
                </div>
                <div class="criteria-item">
                    <div class="ci-num">02</div>
                    <div class="ci-content">
                        <div class="ci-title">마감 양봉 완성도 (윗꼬리 38% 이하)</div>
                        <div class="ci-desc">15:10 장마감까지 차익실현 매물에 밀리지 않고 고가 부근을 단단하게 지켜낸 최상위 매수세 검증</div>
                    </div>
                </div>
                <div class="criteria-item">
                    <div class="ci-num">03</div>
                    <div class="ci-content">
                        <div class="ci-title">과열 없는 최적 상승률 (+3.5% ~ +10.0%)</div>
                        <div class="ci-desc">너무 적게 오르면(+3% 미만) 힘이 없고, 너무 많이 폭등하면(+10% 초과) 다음 날 아침 차익 매물(상투)을 맞기 때문에 갭상승 확률이 가장 높은 '딱 좋은 상승 구간'만 선별</div>
                    </div>
                </div>
                <div class="criteria-item">
                    <div class="ci-num">04</div>
                    <div class="ci-content">
                        <div class="ci-title">익일 시초가 기계적 익절 (+3%~+5%)</div>
                        <div class="ci-desc">익일 아침 09:00~09:20 시초가 갭상승 파동에서 욕심 없이 전량 분할 매도하는 오버나잇 단기 승부 원칙</div>
                    </div>
                </div>
            </div>
        </div>

        <div class="rec-grid">
            {closing_cards_html}
        </div>
    </div>

    <!-- 2) 2~5일 스윙 컨테이너 -->
    <div id="rec-swing-container" class="rec-container" style="display: none;">
        <div class="rec-strategy-banner banner-purple">
            <div>
                <b>🌊 2~5일 스윙 전략 핵심 가이드 ({swing_scan_label} 스캔)</b>: 현재 시장 환경(<b>{swing_regime_label}</b>) 연동 → <b>{swing_regime_summary}</b> (최초 손절 -3%, 최대 5영업일 보유)
            </div>
        </div>

        <!-- 🔍 2~5일 스윙 4대 선별 기준 설명 박스 -->
        <div class="criteria-card">
            <div class="criteria-head">
                <span>🔍 AI 2~5일 스윙 4대 엄격 선별 기준 (추세 파동 승률 모델)</span>
                <span class="criteria-sub-tag tag-purple">안정적 손익비 모델</span>
            </div>
            <div class="criteria-grid">
                <div class="criteria-item">
                    <div class="ci-num num-purple">01</div>
                    <div class="ci-content">
                        <div class="ci-title">20일선 우상향 & 5% 이내 눌림목 지지</div>
                        <div class="ci-desc">중기 추세가 살아있는 종목이 20일선 부근까지 건강하게 조정을 마치고 하방 경직성을 확보한 골든 변곡점 포착</div>
                    </div>
                </div>
                <div class="criteria-item">
                    <div class="ci-num num-purple">02</div>
                    <div class="ci-content">
                        <div class="ci-title">스마트머니 지지 & 거래량 수축</div>
                        <div class="ci-desc">주가가 조정을 받을 때는 매도세가 마르고, 반등할 때 거래대금이 재차 실리는 세력/기관 매집 패턴 확인</div>
                    </div>
                </div>
                <div class="criteria-item">
                    <div class="ci-num num-purple">03</div>
                    <div class="ci-content">
                        <div class="ci-title">시총 4천억 ~ 10조원 알짜 중형주</div>
                        <div class="ci-desc">초대형 지수주(10조 초과)의 무거운 둔화와 소형주(4천억 미만)의 급락 리스크를 모두 피하고, 2~5일 파동 탄력이 가장 뛰어난 알짜 중형 우량주만 선별</div>
                    </div>
                </div>
                <div class="criteria-item">
                    <div class="ci-num num-purple">04</div>
                    <div class="ci-content">
                        <div class="ci-title">3분할 청산 + 본절 스탑 (+3% / +5% / +9%, 손절 -3%)</div>
                        <div class="ci-desc">+3%에서 1/3을 먼저 챙기고 잔량 손절선을 본절로 올려 '수익 난 종목이 손실로 끝나는' 상황을 차단, 나머지 2/3로 +5%·+9% 추세를 끝까지 추종</div>
                    </div>
                </div>
            </div>
        </div>

        <div class="rec-grid">
            {swing_cards_html}
        </div>
        {swing_sim_card_html}
    </div>

    <!-- 3) 당일 +15% 돌파 대장주 컨테이너 -->
    <div id="rec-breakout-container" class="rec-container" style="display: none;">
        <div class="rec-strategy-banner banner-red">
            <div>
                <b>🔥 돌파 대장주 실전 매매 가이드</b>: 당일 종가에 섣불리 추격매수하지 마시고, 향후 2~5영업일간 주가가 5일선/눌림목까지 숨고르기할 때 분할 매수로 공략하는 '기준봉' 관심종목입니다.
            </div>
        </div>

        <!-- 🔍 돌파 대장주 4대 선별 기준 설명 박스 -->
        <div class="criteria-card">
            <div class="criteria-head">
                <span>🔍 AI 당일 +15% 돌파 대장주 4대 엄격 선별 기준 (기준봉 포착 모델)</span>
                <span class="criteria-sub-tag tag-red">시장 주도 대장주 모델</span>
            </div>
            <div class="criteria-grid">
                <div class="criteria-item">
                    <div class="ci-num num-red">01</div>
                    <div class="ci-content">
                        <div class="ci-title">당일 상승률 +14% 이상 장대양봉 돌파</div>
                        <div class="ci-desc">전고점 및 강력한 매물대를 시원하게 뚫어버린 당일 시장 최강 모멘텀 주도주 포착</div>
                    </div>
                </div>
                <div class="criteria-item">
                    <div class="ci-num num-red">02</div>
                    <div class="ci-content">
                        <div class="ci-title">거래대금 200억~500억+ 폭발 (메이저 수급)</div>
                        <div class="ci-desc">시장 자금이 총집결하여 소형 잡주의 가짜 돌파가 아닌 '진짜 메이저 세력/기관 매집' 검증</div>
                    </div>
                </div>
                <div class="criteria-item">
                    <div class="ci-num num-red">03</div>
                    <div class="ci-content">
                        <div class="ci-title">마감 양봉 완성도 (윗꼬리 35% 이하)</div>
                        <div class="ci-desc">장마감까지 차익실현에 무너지지 않고 고가 권역을 견고하게 지켜낸 진짜 대장주만 선별</div>
                    </div>
                </div>
                <div class="criteria-item">
                    <div class="ci-num num-red">04</div>
                    <div class="ci-content">
                        <div class="ci-title">향후 2~5일 눌림목 공략 타겟 (기준봉 활용)</div>
                        <div class="ci-desc">당일 고점 추격매수 절대 금지! 며칠 뒤 5일선·눌림목 반등 시 큰 파동을 안겨줄 핵심 기준봉 후보</div>
                    </div>
                </div>
            </div>
        </div>

        <div class="rec-grid">
            {breakout_cards_html}
        </div>

        <!-- [아이디어 7] 과거 2~7일 내 기준봉 출현 후 오늘 5일선·중심선 눌림목 타점 도래 종목 -->
        <div class="rec-strategy-banner banner-purple" style="margin-top: 24px;">
            <div>
                <b>🎯 [실전 매수 타점 도래] 과거 기준봉(+12%~+15% 돌파) 출현 후 → 오늘 5일선·중심선 + 거래량 건조 눌림목 포착</b><br>
                <span style="font-size:0.8rem; color:#d1d5db;">최근 2~7영업일 내 대량거래 장대양봉(기준봉)을 세운 뒤, 기준봉 시가를 이탈하지 않고 거래량이 65% 이하로 줄어들며 5일선/기준봉 중심선 지지를 받는 실전 맥점 종목입니다.</span>
            </div>
        </div>
        <div class="rec-grid">
            {pullback_cards_html}
        </div>
    </div>

    <!-- 3-B) 키움 내 조건식 ('60일이상추가 1000억') AI 정밀 분석 컨테이너 -->
    <div id="rec-condition-container" class="rec-container" style="display: none;">
        <div class="rec-strategy-banner banner-cyan">
            <div>
                <b>🎯 내 조건식 ('60일이상추가 1000억') 실시간 AI 정밀 채점</b> ({cond_src_badge} · 갱신 <b>{cond_updated_at}</b>): 키움 HTS 조건검색 포착 종목을 종가베팅과 100% 동일한 AI 퀀트 알고리즘(수급·VWAP·윗꼬리·지지저항·DART 공시)으로 채점하여 80점+ S급 타점만 선별합니다.
            </div>
        </div>

        <div class="criteria-card">
            <div class="criteria-head">
                <span>🔍 내 조건식 ('60일이상추가 1000억') ✕ AI 4대 검증 게이트</span>
                <span class="criteria-sub-tag tag-cyan">HTS + 클라우드 하이브리드</span>
            </div>
            <div class="criteria-grid">
                <div class="criteria-item">
                    <div class="ci-num num-cyan">01</div>
                    <div class="ci-content">
                        <div class="ci-title">시총 1,000억+ & 60일 지표 돌파 포착</div>
                        <div class="ci-desc">영웅문 HTS 조건식('60일이상추가 1000억')으로 추출된 종목을 수신하며, PC가 꺼져있을 땐 클라우드 자체 스캔 엔진이 자동 가동됩니다.</div>
                    </div>
                </div>
                <div class="criteria-item">
                    <div class="ci-num num-cyan">02</div>
                    <div class="ci-content">
                        <div class="ci-title">종가베팅과 100% 동일한 AI 채점 (0~99점)</div>
                        <div class="ci-desc">거래대금·시총회전율·윗꼬리 완성도·당일 VWAP·외인/기관 수급·뉴스 공시를 동일 공식으로 채점해 점수순 정렬합니다.</div>
                    </div>
                </div>
                <div class="criteria-item">
                    <div class="ci-num num-cyan">03</div>
                    <div class="ci-content">
                        <div class="ci-title">더블 컨펌(Double Confirm) 교차 검증</div>
                        <div class="ci-desc">AI 종가베팅이나 스윙 추천에도 동시 선정된 종목은 👑 더블컨펌 배지와 +5점 가산점으로 최우선 타점을 표시합니다.</div>
                    </div>
                </div>
                <div class="criteria-item">
                    <div class="ci-num num-cyan">04</div>
                    <div class="ci-content">
                        <div class="ci-title">함정주 경고등 (윗꼬리·설거지·악재공시)</div>
                        <div class="ci-desc">조건식에 떴더라도 윗꼬리 38% 초과·VWAP 이탈·악재 공시가 감지되면 감점 및 ⚠️ 경고 태그를 띄워 추격 매수를 방어합니다.</div>
                    </div>
                </div>
            </div>
        </div>

        <div class="rec-grid">
            {condition_cards_html}
        </div>
    </div>

    <!-- 4) 최근 1개월 종가베팅 성과 히스토리 컨테이너 (1달 경과 시 자동 삭제) -->
    <div id="rec-history-container" class="rec-container" style="display: none;">
        <div class="rec-strategy-banner banner-blue">
            <div>
                <b>📜 최근 30일(1개월) 종가베팅 실전 성과 히스토리</b>: 당일 15:10 추천 종목의 익일 시초가 갭상승 결과가 자동 검증·누적되며, 1달(30일)이 경과한 데이터는 자동으로 영구 삭제됩니다.
            </div>
        </div>
        {history_tab_html}
    </div>

    <!-- 5) 최근 1개월 스윙 성과 히스토리 컨테이너 -->
    <div id="rec-swing-history-container" class="rec-container" style="display: none;">
        <div class="rec-strategy-banner banner-purple">
            <div>
                <b>📊 최근 30일(1개월) 2~5일 스윙 실전 성과 히스토리</b>: 20일선 눌림목 반등 추천 종목의 2~5영업일간 최고가 도달 수익률(3분할: 1차 +3% → 본절 스탑, 2차 +5%, 3차 +9%) 및 손절가 이탈 여부를 정밀 추적·누적 검증합니다.
            </div>
        </div>
        {swing_history_tab_html}
    </div>

    <!-- 6) 업그레이드된 비니stock 200% 활용 천재적 실전 매매 아이디어 10선 탭 컨테이너 -->
    <div id="rec-playbook-container" class="rec-container" style="display: none;">
        <div class="rec-strategy-banner" style="background: linear-gradient(135deg, rgba(16, 185, 129, 0.12), rgba(59, 130, 246, 0.12)); border: 1px solid rgba(16, 185, 129, 0.35); color: #ecfdf5;">
            <div style="font-size: 0.95rem; font-weight: 800; color: #34d399; margin-bottom: 4px;">
                📘 비니stock을 200% 활용하는 천재적 실전 매매 아이디어 10선 (실전 플레이북)
            </div>
            <div style="font-size: 0.83rem; color: #d1d5db;">
                장중·장마감 매매 시 이 탭을 열어두고 <b>[체크 포인트 → 실전 타점 공식]</b>을 하나씩 대조하며 기계적으로 대응하세요. 아래 카테고리 버튼을 누르면 원하는 전략만 골라볼 수 있습니다.
            </div>
        </div>

        <!-- 활용법 내부 서브 카테고리 탭 -->
        <div style="display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 18px; padding: 10px 14px; background: rgba(255,255,255,0.03); border: 1px solid var(--border); border-radius: 10px;">
            <span style="font-size: 0.8rem; font-weight: 700; color: var(--text-sub); display: flex; align-items: center; margin-right: 4px;">📂 전략별 보기:</span>
            <button class="mfilter-btn pb-filter-btn active" onclick="filterPlaybook('all', this)">🌟 전체 10대 공식</button>
            <button class="mfilter-btn pb-filter-btn" onclick="filterPlaybook('timing', this)">⚡ 종가베팅·NXT 시차 (3)</button>
            <button class="mfilter-btn pb-filter-btn" onclick="filterPlaybook('chart', this)">📊 수급·차트 맥점 (3)</button>
            <button class="mfilter-btn pb-filter-btn" onclick="filterPlaybook('event', this)">📢 공시·이벤트 알파 (2)</button>
            <button class="mfilter-btn pb-filter-btn" onclick="filterPlaybook('risk', this)">💰 자금관리·청산 공식 (2)</button>
        </div>

        <div class="rec-grid" style="grid-template-columns: repeat(auto-fit, minmax(340px, 1fr));">
            <!-- 01 -->
            <div class="rec-card pb-card" data-pb-cat="risk" style="border-top: 3px solid #3b82f6;">
                <div class="rec-card-top">
                    <div class="rec-stock-title" style="font-size: 1.02rem; font-weight: 800; color: #60a5fa;">01. [시드 계산기 × 리스크 게이지] 변동성 역가중 베팅</div>
                    <span class="rec-score-badge" style="background:rgba(59,130,246,0.18); color:#93c5fd; border-color:rgba(59,130,246,0.4);">💰 자금관리</span>
                </div>
                <div class="rec-desc-box" style="margin-bottom: 0;">
                    <div style="color:#fbbf24; font-weight:700; font-size:0.8rem; margin-bottom:4px;">👀 대시보드 어디를 보나?</div>
                    <div style="color:var(--text-main); font-size:0.82rem; margin-bottom:8px;">최상단 <b>[🛡️ AI 실시간 시장 리스크 스코어]</b>와 <b>[💰 하프 켈리 실전 시드머니 계산기]</b>의 오늘 권장 총 투입 비중(%)</div>
                    <div style="color:#34d399; font-weight:700; font-size:0.8rem; margin-bottom:4px;">⚡ 실전 매매 공식 (Action Rule)</div>
                    <div style="color:var(--text-main); font-size:0.82rem; margin-bottom:8px;">• 리스크 점수가 <b>65점(경고) 이상</b>일 때는 계산기가 총 투입 비중을 30% 이하로 자동 축소합니다.<br>• 이때 억지로 3종목을 다 사지 말고, <b>추천 1위 대장주 딱 1종목</b>에만 계산기가 알려주는 <code>1종목당 권장 주식 수(주)</code>만큼만 진입하세요.</div>
                    <div style="color:#a78bfa; font-weight:700; font-size:0.78rem;">💡 왜 통하는가?: 하락장에서 계좌가 녹는 유일한 이유는 상승장과 똑같은 비중으로 베팅하기 때문입니다.</div>
                </div>
            </div>

            <!-- 02 -->
            <div class="rec-card pb-card" data-pb-cat="timing" style="border-top: 3px solid #f59e0b;">
                <div class="rec-card-top">
                    <div class="rec-stock-title" style="font-size: 1.02rem; font-weight: 800; color: #fbbf24;">02. [VWAP + 고점 시각] 14:00 이후 고점 경신주 공략</div>
                    <span class="rec-score-badge" style="background:rgba(245,158,11,0.18); color:#fde68a; border-color:rgba(245,158,11,0.4);">⚡ 종가베팅</span>
                </div>
                <div class="rec-desc-box" style="margin-bottom: 0;">
                    <div style="color:#fbbf24; font-weight:700; font-size:0.8rem; margin-bottom:4px;">👀 대시보드 어디를 보나?</div>
                    <div style="color:var(--text-main); font-size:0.82rem; margin-bottom:8px;">종목 카드 내부의 <b>[📈 VWAP +X.X% · 고점 HH:MM]</b> 녹색 배지</div>
                    <div style="color:#34d399; font-weight:700; font-size:0.8rem; margin-bottom:4px;">⚡ 실전 매매 공식 (Action Rule)</div>
                    <div style="color:var(--text-main); font-size:0.82rem; margin-bottom:8px;">• 종가베팅 후보 중 <b>고점 형성 시각이 <code>14:00 ~ 15:20</code> 사이</b>이면서 <b>VWAP 대비 <code>+0.5% ~ +3.0%</code> 위</b>에서 마감하는 종목을 최우선 매수하세요.<br>• 오전 10시 이전에 고점을 찍고 오후 내내 흘러내린 '설거지 종목'은 시스템이 1차로 자동 탈락시킵니다.</div>
                    <div style="color:#a78bfa; font-weight:700; font-size:0.78rem;">💡 왜 통하는가?: 종가가 당일 평균 매수단가(VWAP) 위에 있어야 당일 매수자 전원이 수익권이 되어 익일 시초가 본전 매물이 안 나옵니다.</div>
                </div>
            </div>

            <!-- 03 -->
            <div class="rec-card pb-card" data-pb-cat="chart" style="border-top: 3px solid #10b981;">
                <div class="rec-card-top">
                    <div class="rec-stock-title" style="font-size: 1.02rem; font-weight: 800; color: #34d399;">03. [RVOL × 시총회전율] 'RVOL 3배 + 회전율 5~25%' 공식</div>
                    <span class="rec-score-badge" style="background:rgba(16,185,129,0.18); color:#34d399; border-color:rgba(16,185,129,0.4);">📊 수급·차트</span>
                </div>
                <div class="rec-desc-box" style="margin-bottom: 0;">
                    <div style="color:#fbbf24; font-weight:700; font-size:0.8rem; margin-bottom:4px;">👀 대시보드 어디를 보나?</div>
                    <div style="color:var(--text-main); font-size:0.82rem; margin-bottom:8px;">종목 카드 내부의 <b>[🔥 상대거래량 RVOL X.X배]</b> 및 <b>[💫 시총회전율 X.X%]</b> 배지</div>
                    <div style="color:#34d399; font-weight:700; font-size:0.8rem; margin-bottom:4px;">⚡ 실전 매매 공식 (Action Rule)</div>
                    <div style="color:var(--text-main); font-size:0.82rem; margin-bottom:8px;">• 3개의 추천 종목 중 어디에 비중을 더 실을지 고민될 때, <b><code>RVOL 2.5배~5.0배</code></b>이면서 <b><code>시총회전율 5% ~ 25%</code></b> 사이인 종목을 1순위로 선택하세요.<br>• 회전율이 45%를 초과하면 단타 과열로 익일 시초가 변동성이 커지므로 목표가를 짧게(+2~3%) 잡으세요.</div>
                    <div style="color:#a78bfa; font-weight:700; font-size:0.78rem;">💡 왜 통하는가?: 평소 거래량의 3배 이상이 터졌다는 것은 단순 개인 매수가 아닌 메이저 기관/세력의 신규 자금 유입 증거입니다.</div>
                </div>
            </div>

            <!-- 04 -->
            <div class="rec-card pb-card" data-pb-cat="timing" style="border-top: 3px solid #f59e0b;">
                <div class="rec-card-top">
                    <div class="rec-stock-title" style="font-size: 1.02rem; font-weight: 800; color: #fbbf24;">04. [주도 섹터 동조화] 1위 섹터 대장주 그림자 전략</div>
                    <span class="rec-score-badge" style="background:rgba(245,158,11,0.18); color:#fde68a; border-color:rgba(245,158,11,0.4);">⚡ 종가베팅</span>
                </div>
                <div class="rec-desc-box" style="margin-bottom: 0;">
                    <div style="color:#fbbf24; font-weight:700; font-size:0.8rem; margin-bottom:4px;">👀 대시보드 어디를 보나?</div>
                    <div style="color:var(--text-main); font-size:0.82rem; margin-bottom:8px;">추천 탭 바로 위의 <b>[🔥 오늘의 최강 주도 섹터 TOP 3 (Sector Sympathy)]</b> 배너</div>
                    <div style="color:#34d399; font-weight:700; font-size:0.8rem; margin-bottom:4px;">⚡ 실전 매매 공식 (Action Rule)</div>
                    <div style="color:var(--text-main); font-size:0.82rem; margin-bottom:8px;">• 나홀로 오른 개별주보다 <b>🥇 1위 주도 섹터(폭발 종목 3개 이상)에 속한 종목</b>을 우선 공략하세요.<br>• 익일 아침 09:00 시초가 매도 시에도 해당 섹터의 <b><code>👑 대표 대장주</code></b> 호가가 꺾이는 순간을 전량 익절 타이밍으로 삼으세요.</div>
                    <div style="color:#a78bfa; font-weight:700; font-size:0.78rem;">💡 왜 통하는가?: 섹터 전체에 수천억 원이 쏠린 날은 다음 날 아침에도 기관/외인의 패시브 바스켓 매수가 동반 유입됩니다.</div>
                </div>
            </div>

            <!-- 05 -->
            <div class="rec-card pb-card" data-pb-cat="chart" style="border-top: 3px solid #10b981;">
                <div class="rec-card-top">
                    <div class="rec-stock-title" style="font-size: 1.02rem; font-weight: 800; color: #34d399;">05. [과거 기준봉 눌림목] 거래량 65% 이하 건조 맥점 노리기</div>
                    <span class="rec-score-badge" style="background:rgba(16,185,129,0.18); color:#34d399; border-color:rgba(16,185,129,0.4);">📊 수급·차트</span>
                </div>
                <div class="rec-desc-box" style="margin-bottom: 0;">
                    <div style="color:#fbbf24; font-weight:700; font-size:0.8rem; margin-bottom:4px;">👀 대시보드 어디를 보나?</div>
                    <div style="color:var(--text-main); font-size:0.82rem; margin-bottom:8px;"><code>[🔥 당일 +15% 돌파 대장주]</code> 탭 하단의 <b>[🎯 과거 기준봉 → 오늘 5일선·중심선 눌림목 포착]</b> 섹션</div>
                    <div style="color:#34d399; font-weight:700; font-size:0.8rem; margin-bottom:4px;">⚡ 실전 매매 공식 (Action Rule)</div>
                    <div style="color:var(--text-main); font-size:0.82rem; margin-bottom:8px;">• 급등 당일 추격매수는 금물! 2~7일 뒤 <b>거래량이 기준봉의 35~65% 이하로 바짝 마르면서(숨고르기) 5일선이나 기준봉 중심선에 닿은 종목</b>을 분할 매수하세요.<br>• 손절선은 카드에 적힌 <b><code>기준봉 시가</code></b>로 짧게 잡고 +5%~+10% 반등 파동을 노립니다.</div>
                    <div style="color:#a78bfa; font-weight:700; font-size:0.78rem;">💡 왜 통하는가?: 기준봉에 들어온 수백억 세력 자금은 거래량 없이 빠질 수 없으므로 중심선 부근에서 반드시 기술적 반등이 나옵니다.</div>
                </div>
            </div>

            <!-- 06 -->
            <div class="rec-card pb-card" data-pb-cat="timing" style="border-top: 3px solid #f59e0b;">
                <div class="rec-card-top">
                    <div class="rec-stock-title" style="font-size: 1.02rem; font-weight: 800; color: #fbbf24;">06. [NXT 프리마켓 시차 차익] 08:05 절반(+3.5%) 선제 지정가 매도</div>
                    <span class="rec-score-badge" style="background:rgba(245,158,11,0.18); color:#fde68a; border-color:rgba(245,158,11,0.4);">⚡ NXT 시차</span>
                </div>
                <div class="rec-desc-box" style="margin-bottom: 0;">
                    <div style="color:#fbbf24; font-weight:700; font-size:0.8rem; margin-bottom:4px;">👀 대시보드 어디를 보나?</div>
                    <div style="color:var(--text-main); font-size:0.82rem; margin-bottom:8px;">종목 카드의 <b>[🌙 NXT 프리마켓/야간마켓]</b> 배지 및 하단 <b>[🌅 07:40 / 08:40 매도 가이드]</b></div>
                    <div style="color:#34d399; font-weight:700; font-size:0.8rem; margin-bottom:4px;">⚡ 실전 매매 공식 (Action Rule)</div>
                    <div style="color:var(--text-main); font-size:0.82rem; margin-bottom:8px;">• 전일 종가베팅 보유 종목은 아침 <code>08:00~08:40</code> NXT 프리마켓에서 호가창이 얇아 작은 매수세에도 +3~5% 쉽게 튑니다.<br>• 아침 08:05에 <b>보유 물량의 50%를 <code>+3.5% 지정가 매도</code>로 미리 걸어 선제 익절</b>하고, 나머지 50%만 09:00 정규장 시초가에 대응하세요.</div>
                    <div style="color:#a78bfa; font-weight:700; font-size:0.78rem;">💡 왜 통하는가?: 09:00 정규장 동시호가에 쏟아지는 차익 매물보다 30분 먼저 고가에 수익을 확정할 수 있습니다.</div>
                </div>
            </div>

            <!-- 07 -->
            <div class="rec-card pb-card" data-pb-cat="event" style="border-top: 3px solid #a855f7;">
                <div class="rec-card-top">
                    <div class="rec-stock-title" style="font-size: 1.02rem; font-weight: 800; color: #c084fc;">07. [DART 선반영 판별기] '주가 미반영 알짜 서프라이즈' 공략</div>
                    <span class="rec-score-badge" style="background:rgba(168,85,247,0.18); color:#e9d5ff; border-color:rgba(168,85,247,0.4);">📢 공시 알파</span>
                </div>
                <div class="rec-desc-box" style="margin-bottom: 0;">
                    <div style="color:#fbbf24; font-weight:700; font-size:0.8rem; margin-bottom:4px;">👀 대시보드 어디를 보나?</div>
                    <div style="color:var(--text-main); font-size:0.82rem; margin-bottom:8px;">하단 <code>[📈 실적 발표]</code> 공시 카드 내 <b>[💡 선반영 판별: 🟢 주가 미반영 알짜 호재]</b> 문구</div>
                    <div style="color:#34d399; font-weight:700; font-size:0.8rem; margin-bottom:4px;">⚡ 실전 매매 공식 (Action Rule)</div>
                    <div style="color:var(--text-main); font-size:0.82rem; margin-bottom:8px;">• 컨센서스 대비 +10% 이상 어닝 서프라이즈이면서 <b>최근 10일 주가 등락률이 <code>+7% 이하</code>(🟢 미반영 알짜 호재)</b>인 종목만 공략하세요.<br>• 반대로 <code>⚠️ 단기 급등 선반영 주의(10일 +18% 이상)</code>가 뜬 공시는 재료소멸(Sell the News) 음봉 위험이 크므로 추격매수를 피하세요.</div>
                    <div style="color:#a78bfa; font-weight:700; font-size:0.78rem;">💡 왜 통하는가?: 주가가 오르지 않은 상태에서의 깜짝 실적은 익일 증권사 리포트 상향과 기관 신규 편입(PEAD 효과)을 부릅니다.</div>
                </div>
            </div>

            <!-- 08 -->
            <div class="rec-card pb-card" data-pb-cat="event" style="border-top: 3px solid #a855f7;">
                <div class="rec-card-top">
                    <div class="rec-stock-title" style="font-size: 1.02rem; font-weight: 800; color: #c084fc;">08. [자사주 일일 매수압력] '매수압력 3%+ 초강력 지지주' 바닥 줍기</div>
                    <span class="rec-score-badge" style="background:rgba(168,85,247,0.18); color:#e9d5ff; border-color:rgba(168,85,247,0.4);">📢 공시 알파</span>
                </div>
                <div class="rec-desc-box" style="margin-bottom: 0;">
                    <div style="color:#fbbf24; font-weight:700; font-size:0.8rem; margin-bottom:4px;">👀 대시보드 어디를 보나?</div>
                    <div style="color:var(--text-main); font-size:0.82rem; margin-bottom:8px;">하단 <code>[🔥 자사주·소각]</code> 공시 카드 내 <b>[⚡ 수급 파괴력: 시총 대비 X% | 일일 매수압력 X%]</b></div>
                    <div style="color:#34d399; font-weight:700; font-size:0.8rem; margin-bottom:4px;">⚡ 실전 매매 공식 (Action Rule)</div>
                    <div style="color:var(--text-main); font-size:0.82rem; margin-bottom:8px;">• 자사주 취득 공시 중 <b><code>일일 매수압력이 일평균 거래대금의 3.0% 이상(🔥초강력 하방지지)</code></b>인 종목을 관심종목에 넣어두세요.<br>• 지수가 급락하는 날 이 종목들이 장중 -2~-3% 눌릴 때 저가 매수하면 회사 자사주 자금이 호가창 하단을 받쳐주어 안전하게 반등합니다.</div>
                    <div style="color:#a78bfa; font-weight:700; font-size:0.78rem;">💡 왜 통하는가?: 회사가 매일 장내 거래량의 상당 비율을 기계적으로 사들이므로 강력한 하방 풋옵션(Put Option)이 작동합니다.</div>
                </div>
            </div>

            <!-- 09 -->
            <div class="rec-card pb-card" data-pb-cat="chart" style="border-top: 3px solid #10b981;">
                <div class="rec-card-top">
                    <div class="rec-stock-title" style="font-size: 1.02rem; font-weight: 800; color: #34d399;">09. [30일 오답노트 메타인지] 시장 주도 섹터 순환매(Rotation) 동기화</div>
                    <span class="rec-score-badge" style="background:rgba(16,185,129,0.18); color:#34d399; border-color:rgba(16,185,129,0.4);">📊 메타인지</span>
                </div>
                <div class="rec-desc-box" style="margin-bottom: 0;">
                    <div style="color:#fbbf24; font-weight:700; font-size:0.8rem; margin-bottom:4px;">👀 대시보드 어디를 보나?</div>
                    <div style="color:var(--text-main); font-size:0.82rem; margin-bottom:8px;"><code>[📜 최근 1개월 종가베팅 성과]</code> 탭 상단의 <b>[🧠 AI 30일 오답노트 메타 인사이트 & 자가보정]</b> 배너</div>
                    <div style="color:#34d399; font-weight:700; font-size:0.8rem; margin-bottom:4px;">⚡ 실전 매매 공식 (Action Rule)</div>
                    <div style="color:var(--text-main); font-size:0.82rem; margin-bottom:8px;">• 최근 30일 실제 시초가 승률이 65% 이상인 <b>검증된 고승률 섹터</b>에 속한 종목은 시스템이 자동으로 <code>+4점 자가보정 가산점</code>을 부여합니다.<br>• 이 배너의 1위 섹터가 바뀌는 순간이 시장의 테마 순환매 변곡점이므로 내 스윙 계좌의 섹터 비중도 즉시 일치시키세요.</div>
                    <div style="color:#a78bfa; font-weight:700; font-size:0.78rem;">💡 왜 통하는가?: 내 감(직관)이 아니라 최근 한 달간 실제 시초가 갭을 가장 잘 띄운 섹터 통계에 올라타는 것이 가장 객관적입니다.</div>
                </div>
            </div>

            <!-- 10 -->
            <div class="rec-card pb-card" data-pb-cat="risk" style="border-top: 3px solid #3b82f6;">
                <div class="rec-card-top">
                    <div class="rec-stock-title" style="font-size: 1.02rem; font-weight: 800; color: #60a5fa;">10. [스윙 What-If 3분할 청산] 1차 익절 후 '본절 스탑(무패 잠금)' 공식</div>
                    <span class="rec-score-badge" style="background:rgba(59,130,246,0.18); color:#93c5fd; border-color:rgba(59,130,246,0.4);">💰 청산공식</span>
                </div>
                <div class="rec-desc-box" style="margin-bottom: 0;">
                    <div style="color:#fbbf24; font-weight:700; font-size:0.8rem; margin-bottom:4px;">👀 대시보드 어디를 보나?</div>
                    <div style="color:var(--text-main); font-size:0.82rem; margin-bottom:8px;"><code>[🌊 2~5일 스윙 추천]</code> 탭 하단의 <b>[🎯 스윙 What-If 목표 수익 시뮬레이터]</b> 표</div>
                    <div style="color:#34d399; font-weight:700; font-size:0.8rem; margin-bottom:4px;">⚡ 실전 매매 공식 (Action Rule)</div>
                    <div style="color:var(--text-main); font-size:0.82rem; margin-bottom:8px;">• 시뮬레이터 표의 권장 주식 수(예: 30주) 매수 후 <b>1차 목표가(+3%) 도달 시 1/3(10주)을 즉시 매도</b>하여 수익을 챙기세요.<br>• 동시에 남은 2/3(20주)의 손절선을 <code>-2%</code>에서 <b><code>내 매수 본절가(0%)</code>로 올려두면</b>, 이후 주가가 어떻게 흔들려도 절대 손실이 안 나는 <b>100% 무패(Risk-Free) 포지션</b>으로 2차(+5%)·3차(+9%) 파동을 끝까지 먹을 수 있습니다.</div>
                    <div style="color:#a78bfa; font-weight:700; font-size:0.78rem;">💡 왜 통하는가?: 1차 수익 확정 + 본절 스탑 잠금은 트레이더의 심리적 불안을 제거하여 큰 추세 수익을 끝까지 지키게 해줍니다.</div>
                </div>
            </div>
        </div>
    </div>

    <!-- 2-7. 오늘의 시장 흐름 (머니플로우 전광판) 탭 컨테이너 -->
    <div id="rec-flow-container" class="rec-container" style="display: none;">
        {market_flow_html}
    </div>

    <!-- 3. 실전 4대 종가베팅/매도 가이드 -->
    <div class="section-title" style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px;">
        <span>⏱️ 실전 4대 트레이딩 라이프사이클 가이드</span>
        <span style="font-size: 0.82rem; font-weight: 600; color: #38bdf8; background: rgba(56, 189, 248, 0.12); padding: 4px 12px; border-radius: 12px; border: 1px solid rgba(56, 189, 248, 0.3);">📅 {guide_date_badge}</span>
    </div>
    <div style="font-size: 0.82rem; color: #9ca3af; margin-top: -8px; margin-bottom: 14px;">
        💡 <b>{guide_date_label}</b> 기준 장전 매도(07:40/08:40)부터 장마감 종가베팅(15:10/19:40)까지 4대 시간대별 실시간 대응 전략입니다.
    </div>
    <div class="tabs">
        <button class="tab-btn{t0_act}" onclick="showGuide('g0740', this)">🌅 07:40 NXT 매도</button>
        <button class="tab-btn{t1_act}" onclick="showGuide('g0840', this)">🌅 08:40 정규장 매도</button>
        <button class="tab-btn{t2_act}" onclick="showGuide('g1510', this)">🎯 15:10 정규장 종가베팅</button>
        <button class="tab-btn{t3_act}" onclick="showGuide('g1940', this)">🎯 19:40 NXT 최종 종가베팅</button>
    </div>

    <div id="guide-box" class="guide-content"></div>

    <!-- 3. 핵심 공시 레이더 (실적 · 자사주/소각 · IR 카테고리 분리) -->
    <div class="section-title">
        <span>📢 핵심 공시 레이더 (실적 · 자사주/소각 · IR)</span>
    </div>
    <div style="font-size: 0.8rem; color: #9ca3af; margin-top: -8px; margin-bottom: 16px;">
        💡 <b>⭐ 배지 및 🔥 소각</b>은 알고리즘이 '어닝서프라이즈(+10% 초과)', '흑자전환', '100억 이상 대규모 자사주 취득', '주식 소각' 등 강력한 주주환원 모멘텀을 자동 포착한 공시입니다.
    </div>

    <!-- 카테고리 필터 탭 -->
    <div class="disclosure-nav">
        <button class="disc-tab active" onclick="filterDisclosures('all', this)">
            🌐 전체 공시 <span class="tab-count">{total_disc_count}</span>
        </button>
        <button class="disc-tab" onclick="filterDisclosures('earnings', this)">
            📈 실적 발표 <span class="tab-count count-green">{earnings_count}</span>
        </button>
        <button class="disc-tab" onclick="filterDisclosures('buyback', this)">
            🔥 자사주·소각 <span class="tab-count count-gold">{buyback_count}</span>
        </button>
        <button class="disc-tab" onclick="filterDisclosures('ir', this)">
            🎤 IR 일정 <span class="tab-count count-purple">{ir_count}</span>
        </button>
    </div>

    <!-- 1) 실적 발표 섹션 -->
    <div id="section-earnings" class="category-group">
        <div class="category-header header-green">
            <div class="cat-title">📈 <span>잠정실적 & 어닝 서프라이즈 레이더</span></div>
            <div class="cat-badge">컨센서스 대비 ±10% 판정 · {earnings_count}건</div>
        </div>
        <div class="disclosure-grid">
            {earnings_html or "<div class='empty-card'>최근 24시간 내 등록된 잠정실적 공시가 없습니다.</div>"}
        </div>
    </div>

    <!-- 2) 자사주 취득 & 소각 섹션 -->
    <div id="section-buyback" class="category-group">
        <div class="category-header header-gold">
            <div class="cat-title">🔥 <span>대규모 자사주 취득 & 주식 소각 레이더</span></div>
            <div class="cat-badge">주주환원 · 100억+ 또는 소각 · {buyback_count}건</div>
        </div>
        <div class="disclosure-grid">
            {buyback_html or "<div class='empty-card'>최근 24시간 내 등록된 대규모 자사주 취득(100억+) 또는 주식 소각 공시가 없습니다.</div>"}
        </div>
    </div>

    <!-- 3) IR 일정 섹션 -->
    <div id="section-ir" class="category-group">
        <div class="category-header header-purple">
            <div class="cat-title">🎤 <span>실적발표 및 기업설명회(IR) 일정 레이더</span></div>
            <div class="cat-badge">개최 일시 · 대상 · 방식 · {ir_count}건</div>
        </div>
        <div class="disclosure-grid">
            {ir_html or "<div class='empty-card'>최근 24시간 내 등록된 IR 일정 공시가 없습니다.</div>"}
        </div>
    </div>

    <footer>
        비니stock 자동화 시스템 • 100% 무료 GitHub Pages 호스팅 • 매일 자동 업데이트
    </footer>

    <script>
        const guides = {{
            g0740: `{g0740_js}`,
            g0840: `{g0840_js}`,
            g1510: `{g1510_js}`,
            g1940: `{g1940_js}`
        }};

        function showGuide(key, btn) {{
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            if(btn) btn.classList.add('active');
            const cleanText = guides[key].replace(/<[^>]*>?/gm, '');
            document.getElementById('guide-box').innerText = cleanText;
        }}

        function filterDisclosures(type, btn) {{
            document.querySelectorAll('.disc-tab').forEach(b => b.classList.remove('active'));
            if(btn) btn.classList.add('active');

            const secEarnings = document.getElementById('section-earnings');
            const secBuyback = document.getElementById('section-buyback');
            const secIr = document.getElementById('section-ir');

            if (type === 'all') {{
                secEarnings.style.display = 'block';
                secBuyback.style.display = 'block';
                secIr.style.display = 'block';
            }} else if (type === 'earnings') {{
                secEarnings.style.display = 'block';
                secBuyback.style.display = 'none';
                secIr.style.display = 'none';
            }} else if (type === 'buyback') {{
                secEarnings.style.display = 'none';
                secBuyback.style.display = 'block';
                secIr.style.display = 'none';
            }} else if (type === 'ir') {{
                secEarnings.style.display = 'none';
                secBuyback.style.display = 'none';
                secIr.style.display = 'block';
            }}
        }}

        // 현재 시간대 맞춤 기본 활성 가이드 탭 로드
        showGuide('{def_guide_key}', document.querySelectorAll('.tab-btn')[{def_guide_idx}]);

        function switchRecTrack(track, btn) {{
            document.querySelectorAll('.rec-tab').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            document.getElementById('rec-closing-container').style.display = (track === 'closing') ? 'block' : 'none';
            document.getElementById('rec-swing-container').style.display = (track === 'swing') ? 'block' : 'none';
            document.getElementById('rec-breakout-container').style.display = (track === 'breakout') ? 'block' : 'none';
            const condEl = document.getElementById('rec-condition-container');
            if (condEl) condEl.style.display = (track === 'condition') ? 'block' : 'none';
            document.getElementById('rec-history-container').style.display = (track === 'history') ? 'block' : 'none';
            document.getElementById('rec-swing-history-container').style.display = (track === 'swing_history') ? 'block' : 'none';
            const pbEl = document.getElementById('rec-playbook-container');
            if (pbEl) pbEl.style.display = (track === 'playbook') ? 'block' : 'none';
            const flowEl = document.getElementById('rec-flow-container');
            if (flowEl) flowEl.style.display = (track === 'flow') ? 'block' : 'none';
        }}

        function filterFlowSectors(type, btn) {{
            document.querySelectorAll('.tmf-filter-btn').forEach(b => b.classList.remove('active'));
            if (btn) btn.classList.add('active');
            document.querySelectorAll('.tmf-card').forEach(card => {{
                const dir = card.getAttribute('data-direction');
                const stars = card.getAttribute('data-stars') || '';
                if (type === 'all') {{
                    card.style.display = 'flex';
                }} else if (type === 'UP') {{
                    card.style.display = (dir === 'UP') ? 'flex' : 'none';
                }} else if (type === 'DOWN') {{
                    card.style.display = (dir === 'DOWN') ? 'flex' : 'none';
                }} else if (type === 'STAR') {{
                    card.style.display = (stars.indexOf('⭐️⭐️') !== -1) ? 'flex' : 'none';
                }}
            }});
        }}

        if (window.location.hash === '#tab-flow') {{
            const flowTab = document.querySelector('.rec-tab.tab-rose');
            if (flowTab) switchRecTrack('flow', flowTab);
        }}

        function filterPlaybook(cat, btn) {{
            document.querySelectorAll('.pb-filter-btn').forEach(b => b.classList.remove('active'));
            if (btn) btn.classList.add('active');
            document.querySelectorAll('.pb-card').forEach(card => {{
                const c = card.getAttribute('data-pb-cat');
                card.style.display = (cat === 'all' || c === cat) ? 'flex' : 'none';
            }});
        }}

        // 시가총액 필터
        function filterByMarcap(type, btn) {{
            document.querySelectorAll('.mfilter-btn').forEach(b => b.classList.remove('active'));
            if (btn) btn.classList.add('active');
            document.querySelectorAll('.rec-card').forEach(card => {{
                const marcap = parseFloat(card.getAttribute('data-marcap') || '0');
                const eok = marcap / 1e8;
                if (type === 'all') {{
                    card.style.display = 'flex';
                }} else if (type === 'large') {{
                    card.style.display = (eok >= 10000) ? 'flex' : 'none';
                }} else if (type === 'mid') {{
                    card.style.display = (eok >= 3000 && eok < 10000) ? 'flex' : 'none';
                }} else if (type === 'small') {{
                    card.style.display = (eok < 3000) ? 'flex' : 'none';
                }}
            }});
        }}

        // 실시간 새로고침 (캐시 무시 강제 요청)
        function refreshDashboardNow() {{
            const btns = document.querySelectorAll('.refresh-btn, .risk-quick-refresh-btn');
            btns.forEach(b => {{
                b.innerHTML = '🔄 <span class="spin">동기화 중...</span>';
                b.disabled = true;
            }});
            const url = window.location.pathname + '?nocache=' + Date.now();
            fetch(url, {{ cache: 'no-store' }})
                .then(() => {{
                    window.location.href = url;
                }})
                .catch(() => {{
                    window.location.reload();
                }});
        }}

        // 클라우드 모달 열기/닫기
        function openCloudModal() {{
            const m = document.getElementById('cloud-modal');
            if (m) m.style.display = 'flex';
            const saved = localStorage.getItem('binistock_gh_token');
            const inp = document.getElementById('gh-token-input');
            if (saved && inp) {{
                inp.value = saved;
                const status = document.getElementById('token-status');
                if (status) {{
                    status.style.color = '#34d399';
                    status.innerHTML = '✅ 이 기기에 토큰이 저장되어 있습니다. 바로 <b>[🚀 즉시 실행]</b>만 누르세요!';
                }}
            }}
        }}

        function closeCloudModal() {{
            const m = document.getElementById('cloud-modal');
            if (m) m.style.display = 'none';
        }}

        // GitHub Actions Workflow Dispatch 실행 (모바일 / 외부 PC용)
        function saveAndTriggerWorkflow() {{
            const inp = document.getElementById('gh-token-input');
            const status = document.getElementById('token-status');
            const token = inp ? inp.value.trim() : '';
            if (!token) {{
                if (status) {{
                    status.style.color = '#f87171';
                    status.innerText = '❌ GitHub 토큰을 입력해 주세요. (또는 방법 1을 이용하세요)';
                }}
                return;
            }}
            localStorage.setItem('binistock_gh_token', token);
            if (status) {{
                status.style.color = '#60a5fa';
                status.innerHTML = '⏳ 깃허브 클라우드 서버에 실시간 재분석 요청을 전송 중...';
            }}

            fetch('https://api.github.com/repos/parkseungbin1/binistock/actions/workflows/deploy-web.yml/dispatches', {{
                method: 'POST',
                headers: {{
                    'Accept': 'application/vnd.github.v3+json',
                    'Authorization': 'token ' + token,
                    'Content-Type': 'application/json'
                }},
                body: JSON.stringify({{ ref: 'main' }})
            }})
            .then(res => {{
                if (res.status === 204 || res.ok) {{
                    if (status) {{
                        status.style.color = '#34d399';
                        status.innerHTML = '🚀 <b>성공!</b> 클라우드에서 실시간 재분석이 시작되었습니다. (약 1분 후 최신 데이터가 자동 반영됩니다)';
                    }}
                    setTimeout(() => {{ refreshDashboardNow(); }}, 60000);
                }} else {{
                    return res.json().then(data => {{
                        throw new Error(data.message || '인증 실패 (권한 부족 또는 잘못된 토큰)');
                    }});
                }}
            }})
            .catch(err => {{
                if (status) {{
                    status.style.color = '#f87171';
                    status.innerText = '❌ 실행 실패: ' + err.message + ' (방법 1 링크를 직접 이용해 보세요)';
                }}
            }});
        }}

        // 테마 (다크/라이트) 관리
        function initTheme() {{
            const saved = localStorage.getItem('binistock_theme');
            if (saved === 'light') {{
                document.documentElement.setAttribute('data-theme', 'light');
                const tText = document.getElementById('theme-btn-text');
                if (tText) tText.innerText = '다크모드';
            }}
        }}
        function toggleTheme() {{
            const current = document.documentElement.getAttribute('data-theme');
            const target = (current === 'light') ? 'dark' : 'light';
            if (target === 'light') {{
                document.documentElement.setAttribute('data-theme', 'light');
                localStorage.setItem('binistock_theme', 'light');
                const tText = document.getElementById('theme-btn-text');
                if (tText) tText.innerText = '다크모드';
            }} else {{
                document.documentElement.removeAttribute('data-theme');
                localStorage.setItem('binistock_theme', 'dark');
                const tText = document.getElementById('theme-btn-text');
                if (tText) tText.innerText = '라이트모드';
            }}
        }}
        initTheme();

        // [아이디어 9] 리스크 스코어 × 하프 켈리(Half-Kelly) 시드머니 & 전 종목 매수수량 실시간 계산기
        const AI_RECOMMENDED_PCT = {recommended_invest_pct};
        function initKellySeed() {{
            const savedSeed = localStorage.getItem('binistock_seed_manwon');
            const inp = document.getElementById('seed-money-input');
            if (savedSeed && inp) {{
                inp.value = savedSeed;
            }}
            updateKellyCalculator();
        }}
        function updateKellyCalculator() {{
            const inp = document.getElementById('seed-money-input');
            let seedManwon = inp ? parseFloat(inp.value) : 1000;
            if (isNaN(seedManwon) || seedManwon <= 0) seedManwon = 1000;
            localStorage.setItem('binistock_seed_manwon', seedManwon);

            const totalWon = seedManwon * 10000;
            const investWon = Math.round(totalWon * (AI_RECOMMENDED_PCT / 100.0));
            const cashWon = totalWon - investWon;
            const perStockWon = Math.round(investWon / 3.0);
            const maxLossWon = Math.round(perStockWon * 0.02);

            const fmtMan = (w) => Math.round(w / 10000).toLocaleString() + '만원 (' + w.toLocaleString() + '원)';
            const elTotal = document.getElementById('kelly-total-invest');
            const elCash = document.getElementById('kelly-cash-reserve');
            const elPer = document.getElementById('kelly-per-stock');
            const elLoss = document.getElementById('kelly-max-loss');

            if (elTotal) elTotal.innerText = fmtMan(investWon);
            if (elCash) elCash.innerText = fmtMan(cashWon);
            if (elPer) elPer.innerText = Math.round(perStockWon / 10000).toLocaleString() + '만원';
            if (elLoss) elLoss.innerText = '-' + maxLossWon.toLocaleString() + '원';

            // 모든 추천 종목 카드의 권장 주문 수량 업데이트
            document.querySelectorAll('.rec-kelly-order-box').forEach(box => {{
                const price = parseFloat(box.getAttribute('data-price') || '0');
                if (price > 0) {{
                    const shares = Math.max(1, Math.floor(perStockWon / price));
                    const actualAmt = shares * price;
                    const expProfit = Math.round(actualAmt * 0.03);
                    const expLoss = Math.round(actualAmt * 0.02);
                    box.innerHTML = `💰 <b>시드 연동 권장 주문</b>: <b>${{shares.toLocaleString()}}주</b> (${{actualAmt.toLocaleString()}}원) | +3% 익절 <b>+${{expProfit.toLocaleString()}}원</b> / -2% 손절 <b>-${{expLoss.toLocaleString()}}원</b>`;
                }}
            }});

            // 스윙 What-If 시뮬레이터 표의 시드 연동 열 업데이트
            document.querySelectorAll('.sim-kelly-cell').forEach(cell => {{
                const price = parseFloat(cell.getAttribute('data-price') || '0');
                if (price > 0) {{
                    const shares = Math.max(1, Math.floor(perStockWon / price));
                    const actualAmt = shares * price;
                    const p5 = Math.round(actualAmt * 0.05);
                    const l2 = Math.round(actualAmt * 0.02);
                    cell.innerHTML = `<span style="color:#fbbf24; font-weight:700;">${{shares.toLocaleString()}}주</span> <span style="font-size:0.75rem; color:#9ca3af;">(+5%시 <b style="color:#34d399;">+${{p5.toLocaleString()}}원</b> / 손절 <b style="color:#f87171;">-${{l2.toLocaleString()}}원</b>)</span>`;
                }}
            }});
        }}
        initKellySeed();

        // PWA Service Worker 등록
        if ('serviceWorker' in navigator) {{
            window.addEventListener('load', () => {{
                navigator.serviceWorker.register('./sw.js').catch(() => {{}});
            }});
        }}
    </script>
</body>
</html>
"""
    # 저장 디렉토리 (dist/)
    import shutil
    out_dir = Path(__file__).parent / "dist"
    out_dir.mkdir(exist_ok=True)
    out_file = out_dir / "index.html"
    out_file.write_text(html, encoding="utf-8")

    # PWA 에셋 dist에 복사
    manifest_src = Path(__file__).parent / "manifest.json"
    if manifest_src.exists():
        shutil.copy(manifest_src, out_dir / "manifest.json")
    sw_src = Path(__file__).parent / "sw.js"
    if sw_src.exists():
        shutil.copy(sw_src, out_dir / "sw.js")

    print(f"✓ 웹 대시보드 생성 완료: {out_file} ({out_file.stat().st_size} bytes)")
    return out_file


if __name__ == "__main__":
    generate_html()
