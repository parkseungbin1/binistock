"""
BiniStock 📅 주요일정 & 모멘텀 레이더 전용 HTML 뷰어 (src/calendar_view.py)
- 오버나잇 리스크 가드 배너 (금요일 100% 현금 보존 / 평일 야간 지표 쇼크 방어)
- D-Day 파생 만기일 & 주요 거시 일정 카운트다운 4열 카드
- 확정된 주주환원 주식 소각 레이더 (시총 대비 소각 비중 % 정밀 산출)
- 글로벌 주요 산업 박람회 & 학회 D-Day 타임라인
- 이번 주 글로벌 경제지표 (ForexFactory + 네이버 연동)
"""
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


def render_calendar_dashboard_html(event_intel: dict) -> str:
    if not event_intel:
        return '<div class="empty-card">주요일정 및 모멘텀 데이터를 불러오는 중입니다...</div>'

    overnight_risk = event_intel.get("overnight_risk", {})
    derivatives = event_intel.get("derivatives", {})
    upcoming_catalysts = event_intel.get("upcoming_catalysts", [])
    burn_catalysts = event_intel.get("burn_catalysts", [])
    updated_at = event_intel.get("updated_at", "")

    # ---------------------------------------------------------
    # 1. 오버나잇 리스크 가드 배너
    # ---------------------------------------------------------
    is_friday = overnight_risk.get("is_friday", False)
    risk_score = overnight_risk.get("score", 0)
    risk_level = overnight_risk.get("level", "GREEN")
    status_msg = overnight_risk.get("status_message", "")

    if is_friday:
        banner_bg = "linear-gradient(135deg, rgba(239, 68, 68, 0.18) 0%, rgba(139, 92, 246, 0.18) 100%)"
        banner_border = "#f59e0b"
        banner_badge_bg = "rgba(245, 158, 11, 0.25)"
        banner_badge_color = "#fbbf24"
        banner_icon = "🛡️"
        banner_title = "금요일 주말 리스크 방어 모드 가동 중 (100% 현금 보존 권장)"
        banner_desc = (
            "평일 오버나잇(17.5시간)과 달리 <b>주말은 65.5시간 동안 거래소가 완전히 닫혀 손절(-2%) 대응이 불가능</b>합니다.<br>"
            "토·일요일 돌발 전쟁/지정학 악재나 나스닥 급락으로 인한 월요일 시초가 갭하락(-5~-10%)을 방어하기 위해 <b>신규 매수를 중단하고 전량 현금 보유</b>를 권장합니다."
        )
    elif risk_level == "RED":
        banner_bg = "linear-gradient(135deg, rgba(239, 68, 68, 0.25) 0%, rgba(185, 28, 28, 0.25) 100%)"
        banner_border = "#ef4444"
        banner_badge_bg = "rgba(239, 68, 68, 0.3)"
        banner_badge_color = "#fca5a5"
        banner_icon = "🚨"
        banner_title = f"오늘 밤 초고위험 경제지표 감지 (Risk Score: {risk_score}점 / 🔴 RED)"
        banner_desc = (
            f"오늘 밤 <b>미국 CPI, FOMC, 또는 고용지표 등 시장 충격도가 매우 높은 거시 이벤트</b>가 예정되어 있습니다.<br>"
            "익일 갭하락 리스크를 피하기 위해 오늘 15:10 종가베팅은 <b>전면 매수 차단(100% 현금 오버나잇)</b>을 강력 권장합니다."
        )
    elif risk_level == "YELLOW":
        banner_bg = "linear-gradient(135deg, rgba(245, 158, 11, 0.2) 0%, rgba(217, 119, 6, 0.15) 100%)"
        banner_border = "#f59e0b"
        banner_badge_bg = "rgba(245, 158, 11, 0.25)"
        banner_badge_color = "#fbbf24"
        banner_icon = "⚠️"
        banner_title = f"오늘 밤 주요 지표 발표 예정 (Risk Score: {risk_score}점 / 🟡 YELLOW)"
        banner_desc = (
            f"오늘 밤 중간 영향도의 경제지표가 예정되어 있습니다.<br>"
            "손익비를 방어하기 위해 오늘 15:10 종가베팅은 <b>투자금을 50%로 축소(하프 켈리 적용)</b>하거나 1종목으로 압축 대응을 권장합니다."
        )
    else:
        banner_bg = "linear-gradient(135deg, rgba(16, 185, 129, 0.18) 0%, rgba(5, 150, 105, 0.15) 100%)"
        banner_border = "#10b981"
        banner_badge_bg = "rgba(16, 185, 129, 0.25)"
        banner_badge_color = "#34d399"
        banner_icon = "🟢"
        banner_title = f"오늘 밤 야간 리스크 안전 구간 (Risk Score: {risk_score}점 / 🟢 GREEN)"
        banner_desc = (
            "오늘 밤 시장을 뒤흔들 고위험 경제지표가 없습니다.<br>"
            "AI 점수 80점 이상의 주도주 종목에 대해 <b>정상 100% 종가베팅 오버나잇 진입이 허용</b>됩니다."
        )

    # 감지된 야간 이벤트 리스트
    detected_html = ""
    det_events = overnight_risk.get("detected_events", [])
    if det_events:
        chips = []
        for de in det_events:
            chips.append(f"<span style='background:rgba(255,255,255,0.08); padding:3px 8px; border-radius:6px; font-size:0.75rem; color:#f3f4f6;'>⏰ {de.get('time', '')} {de.get('country', '')} {de.get('desc', de.get('event', ''))}</span>")
        detected_html = f"<div style='margin-top:10px; display:flex; flex-wrap:wrap; gap:6px;'>{''.join(chips)}</div>"

    banner_html = f"""
    <div style="background:{banner_bg}; border:1.5px solid {banner_border}; border-radius:14px; padding:18px 22px; margin-bottom:24px; box-shadow:0 6px 20px rgba(0,0,0,0.25);">
        <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:10px; margin-bottom:8px;">
            <div style="display:flex; align-items:center; gap:8px;">
                <span style="font-size:1.4rem;">{banner_icon}</span>
                <span style="font-size:1.05rem; font-weight:800; color:#ffffff;">{banner_title}</span>
            </div>
            <span style="background:{banner_badge_bg}; color:{banner_badge_color}; border:1px solid {banner_border}; padding:3px 12px; border-radius:999px; font-size:0.8rem; font-weight:800;">
                {status_msg}
            </span>
        </div>
        <div style="font-size:0.85rem; line-height:1.55; color:#e5e7eb;">
            {banner_desc}
        </div>
        {detected_html}
    </div>
    """

    # ---------------------------------------------------------
    # 2. D-Day 파생상품 & 주요 일정 카드 4종
    # ---------------------------------------------------------
    next_kr = derivatives.get("next_kr") or {}
    next_quad = derivatives.get("next_quadruple") or {}
    all_derivs = derivatives.get("all_upcoming") or []
    next_us = next((c for c in all_derivs if c.get("country") == "미국"), {})
    msci = next((c for c in upcoming_catalysts if "MSCI" in c.get("category", "")), {})
    bok = next((c for c in upcoming_catalysts if "BOK" in c.get("category", "")), {})

    def _d_badge(d):
        if d is None:
            return "D-?"
        if d == 0:
            return "🔥 D-Day"
        return f"D-{d}"

    kr_quad_badge = "🔥 네 마녀의 날" if next_kr.get("is_quadruple") else "옵션만기"

    cards_html = f"""
    <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(240px, 1fr)); gap:14px; margin-bottom:28px;">
        <!-- 카드 1: 국내 파생만기일 -->
        <div style="background:var(--surface); border:1px solid rgba(59, 130, 246, 0.4); border-top:3px solid #3b82f6; border-radius:12px; padding:16px; display:flex; flex-direction:column; gap:6px;">
            <div style="display:flex; justify-content:space-between; align-items:center;">
                <span style="font-size:0.8rem; color:#93c5fd; font-weight:700;">🇰🇷 국내 파생 만기일</span>
                <span style="background:rgba(59, 130, 246, 0.2); color:#60a5fa; border:1px solid rgba(59, 130, 246, 0.4); font-size:0.75rem; font-weight:800; padding:2px 8px; border-radius:6px;">{_d_badge(next_kr.get('d_day'))}</span>
            </div>
            <div style="font-size:1.05rem; font-weight:800; color:#ffffff;">{next_kr.get('date', '-')}</div>
            <div style="font-size:0.78rem; color:#9ca3af;">
                🏷️ {next_kr.get('name', '국내 옵션만기일')}<br>
                💡 <span style="color:#60a5fa; font-weight:700;">{kr_quad_badge}</span> · 장마감 동시호가 변동성 주의
            </div>
        </div>

        <!-- 카드 2: 미국 옵션만기일 -->
        <div style="background:var(--surface); border:1px solid rgba(139, 92, 246, 0.4); border-top:3px solid #8b5cf6; border-radius:12px; padding:16px; display:flex; flex-direction:column; gap:6px;">
            <div style="display:flex; justify-content:space-between; align-items:center;">
                <span style="font-size:0.8rem; color:#c4b5fd; font-weight:700;">🇺🇸 미국 옵션 만기일</span>
                <span style="background:rgba(139, 92, 246, 0.2); color:#a78bfa; border:1px solid rgba(139, 92, 246, 0.4); font-size:0.75rem; font-weight:800; padding:2px 8px; border-radius:6px;">{_d_badge(next_us.get('d_day'))}</span>
            </div>
            <div style="font-size:1.05rem; font-weight:800; color:#ffffff;">{next_us.get('date', '-')}</div>
            <div style="font-size:0.78rem; color:#9ca3af;">
                🏷️ {next_us.get('name', '미국 옵션만기일')}<br>
                💡 뉴욕 증시 매월 셋째 주 금요일 파생 청산
            </div>
        </div>

        <!-- 카드 3: MSCI 정기변경 -->
        <div style="background:var(--surface); border:1px solid rgba(245, 158, 11, 0.4); border-top:3px solid #f59e0b; border-radius:12px; padding:16px; display:flex; flex-direction:column; gap:6px;">
            <div style="display:flex; justify-content:space-between; align-items:center;">
                <span style="font-size:0.8rem; color:#fde68a; font-weight:700;">💰 MSCI 리밸런싱</span>
                <span style="background:rgba(245, 158, 11, 0.2); color:#fbbf24; border:1px solid rgba(245, 158, 11, 0.4); font-size:0.75rem; font-weight:800; padding:2px 8px; border-radius:6px;">{_d_badge(msci.get('d_day'))}</span>
            </div>
            <div style="font-size:1.05rem; font-weight:800; color:#ffffff;">{msci.get('date', '-')}</div>
            <div style="font-size:0.78rem; color:#9ca3af;">
                🏷️ {msci.get('title', 'MSCI 반기 리뷰')}<br>
                💡 <span style="color:#fbbf24; font-weight:700;">패시브 수천억 유입</span> · 편입 유력주 종가베팅 타겟
            </div>
        </div>

        <!-- 카드 4: 한국은행 금통위 -->
        <div style="background:var(--surface); border:1px solid rgba(16, 185, 129, 0.4); border-top:3px solid #10b981; border-radius:12px; padding:16px; display:flex; flex-direction:column; gap:6px;">
            <div style="display:flex; justify-content:space-between; align-items:center;">
                <span style="font-size:0.8rem; color:#a7f3d0; font-weight:700;">🏛️ 한국은행 금통위</span>
                <span style="background:rgba(16, 185, 129, 0.2); color:#34d399; border:1px solid rgba(16, 185, 129, 0.4); font-size:0.75rem; font-weight:800; padding:2px 8px; border-radius:6px;">{_d_badge(bok.get('d_day'))}</span>
            </div>
            <div style="font-size:1.05rem; font-weight:800; color:#ffffff;">{bok.get('date', '-')}</div>
            <div style="font-size:0.78rem; color:#9ca3af;">
                🏷️ 한국은행 기준금리 결정 회의<br>
                💡 금융/건설/환율 섹터 변동성 분기점
            </div>
        </div>
    </div>
    """

    # ---------------------------------------------------------
    # 3. 확정된 주주환원 자사주 소각 레이더 (시총 대비 비중 % 정밀 산출)
    # ---------------------------------------------------------
    burn_rows_html = []
    for b in burn_catalysts[:6]:
        ratio = b.get("ratio_pct", 0.0)
        boost = b.get("boost_score", 0)
        b_d = b.get("d_day")
        d_str = f"D-{b_d}" if b_d is not None and b_d >= 0 else "예정"

        if boost >= 10:
            badge_html = '<span style="background:rgba(239,68,68,0.22); color:#f87171; border:1px solid rgba(239,68,68,0.4); padding:2px 8px; border-radius:6px; font-weight:800; font-size:0.75rem;">🔥 초특급 (+10점)</span>'
        elif boost >= 7:
            badge_html = '<span style="background:rgba(245,158,11,0.22); color:#fbbf24; border:1px solid rgba(245,158,11,0.4); padding:2px 8px; border-radius:6px; font-weight:800; font-size:0.75rem;">🚀 대형호재 (+7점)</span>'
        elif boost >= 4:
            badge_html = '<span style="background:rgba(59,130,246,0.22); color:#60a5fa; border:1px solid rgba(59,130,246,0.4); padding:2px 8px; border-radius:6px; font-weight:800; font-size:0.75rem;">✨ 일반호재 (+4점)</span>'
        else:
            badge_html = '<span style="background:rgba(156,163,175,0.15); color:#9ca3af; padding:2px 8px; border-radius:6px; font-size:0.75rem;">⚪ 단순소각</span>'

        burn_rows_html.append(f"""
        <div style="background:rgba(255,255,255,0.02); border:1px solid var(--border); border-radius:10px; padding:12px 16px; display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px;">
            <div style="display:flex; align-items:center; gap:10px;">
                <span style="font-weight:800; font-size:0.95rem; color:#ffffff;">{b.get('corp_name')}</span>
                <span style="font-size:0.8rem; background:rgba(239,68,68,0.15); color:#fca5a5; padding:2px 8px; border-radius:6px; font-weight:700;">시총 대비 {ratio:.2f}% 소각</span>
                <span style="font-size:0.75rem; color:#9ca3af;">예정일: {b.get('burn_date', '-')} ({d_str})</span>
            </div>
            <div>
                {badge_html}
            </div>
        </div>
        """)

    burn_section_html = f"""
    <div style="background:var(--surface); border:1px solid var(--border); border-radius:14px; padding:20px; margin-bottom:28px;">
        <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:10px; margin-bottom:14px;">
            <div>
                <span style="font-size:1.05rem; font-weight:800; color:#fbbf24;">🔥 확정된 주주환원: 자사주 영구 소각 레이더</span>
                <div style="font-size:0.78rem; color:#9ca3af; margin-top:3px;">
                    💡 1조짜리 100억 소각(1%)은 노이즈지만, <b>시총 대비 5~7% 이상 대규모 소각은 유통주식이 영구 증발하여 1주당 가치(EPS)가 직접 상승</b>하는 최상급 호재입니다.
                </div>
            </div>
            <span style="font-size:0.75rem; color:#9ca3af;">DART 실시간 공시 연동</span>
        </div>
        <div style="display:flex; flex-direction:column; gap:8px;">
            {''.join(burn_rows_html) if burn_rows_html else '<div class="empty-card">최근 30일 이내 공시된 유효 자사주 소각 건이 없습니다.</div>'}
        </div>
    </div>
    """

    # ---------------------------------------------------------
    # 4. 글로벌 산업 박람회 & 학회 (호재 D-Day)
    # ---------------------------------------------------------
    expo_items = [c for c in upcoming_catalysts if c.get("category") == "EXPO_CONFERENCE"]
    expo_cards_html = []
    for ex in expo_items:
        sec_tags = "".join([f"<span style='background:rgba(20,184,166,0.15); color:#2dd4bf; border:1px solid rgba(20,184,166,0.3); font-size:0.72rem; padding:2px 6px; border-radius:4px;'>#{s}</span>" for s in ex.get("sectors", [])])
        impact_badge = "🔥 최상급 모멘텀" if ex.get("impact") == "HIGH" else ("⚠️ 경영진 변동성 주의" if ex.get("impact") == "WATCH" else "✨ 주요 모멘텀")
        expo_cards_html.append(f"""
        <div style="background:rgba(255,255,255,0.02); border:1px solid rgba(20, 184, 166, 0.35); border-radius:10px; padding:14px 16px; display:flex; flex-direction:column; gap:6px;">
            <div style="display:flex; justify-content:space-between; align-items:center;">
                <span style="font-size:0.95rem; font-weight:800; color:#2dd4bf;">{ex.get('title')}</span>
                <span style="background:rgba(20, 184, 166, 0.2); color:#5eead4; font-size:0.75rem; font-weight:800; padding:2px 8px; border-radius:6px;">{_d_badge(ex.get('d_day'))} ({ex.get('date')})</span>
            </div>
            <div style="font-size:0.78rem; color:#d1d5db; line-height:1.45;">
                {ex.get('description', '')}
            </div>
            <div style="display:flex; justify-content:space-between; align-items:center; margin-top:4px; flex-wrap:wrap; gap:6px;">
                <div style="display:flex; gap:4px; flex-wrap:wrap;">{sec_tags}</div>
                <span style="font-size:0.72rem; color:#fde68a; font-weight:700;">{impact_badge}</span>
            </div>
        </div>
        """)

    expo_section_html = f"""
    <div style="background:var(--surface); border:1px solid var(--border); border-radius:14px; padding:20px; margin-bottom:28px;">
        <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:10px; margin-bottom:14px;">
            <div>
                <span style="font-size:1.05rem; font-weight:800; color:#2dd4bf;">🎪 글로벌 주요 산업 박람회 & 학회 (D-Day 모멘텀)</span>
                <div style="font-size:0.78rem; color:#9ca3af; margin-top:3px;">
                    💡 글로벌 전시회/학회는 <b>개최 3~7일 전 선취매 랠리</b>가 발생하며, 행사 당일에는 재료소멸 차익실현으로 대응합니다. (오너리스크 발생 시 맹목적 매수 금지)
                </div>
            </div>
            <span style="font-size:0.75rem; color:#9ca3af;">연간 공식 마스터 캘린더</span>
        </div>
        <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(300px, 1fr)); gap:12px;">
            {''.join(expo_cards_html) if expo_cards_html else '<div class="empty-card">향후 45일 이내 예정된 대형 글로벌 전시회/학회가 없습니다.</div>'}
        </div>
    </div>
    """

    return f"""
    <div style="display:flex; flex-direction:column; gap:6px;">
        <!-- 상단 헤더 안내문 -->
        <div style="font-size:0.8rem; color:#9ca3af; margin-bottom:12px; display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:6px;">
            <span>💡 <b>BiniStock 인텔리전스</b>: 야간 경제지표 폭탄을 피하는 <b>방패(Risk Guard)</b>와 확정된 호재 일정을 선취매하는 <b>창(Catalyst Booster)</b>을 실시간 가동합니다.</span>
            <span style="font-size:0.75rem; color:#38bdf8;">동기화: {updated_at}</span>
        </div>

        {banner_html}
        {cards_html}
        {burn_section_html}
        {expo_section_html}
    </div>
    """

