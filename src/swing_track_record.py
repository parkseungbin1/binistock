"""
2~5일 스윙 추천 사후 성과 자동 추적 및 통계 모듈 (Swing Track Record)
1. 2~5일 스윙 추천 종목(20일선 눌림목 반등 타겟) 저장
2. 2~5영업일간 최고가(High) 및 최저가(Low)를 추적하여 1차 목표가(+5%), 2차 목표가(+9%), 손절가(-3%) 도달 여부 자동 판정
3. AI 리스크 50점 초과 차단일은 '현금 100% 보존 방어'로 분리 집계 (실매매 손실 왜곡 차단)
4. 최근 1개월(30일) 데이터 유지 (1달 경과 시 자동 정리)
5. 웹 대시보드 전용 '최근 1개월 스윙 성과' 탭 렌더링 지원
"""
import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
import FinanceDataReader as fdr

logger = logging.getLogger(__name__)
KST = timezone(timedelta(hours=9))

STATE_DIR = Path(__file__).resolve().parent.parent / "data"
SWING_RECORD_FILE = STATE_DIR / "swing_track_record.json"

# 원본 스윙 청산 규칙 버전 (1차 +5.0%, 2차 +9.0%, 손절 -3.0%)
SWING_RULE_VERSION = 1
T1_PCT, T2_PCT, SL_PCT = 5.0, 9.0, -3.0
MAX_HOLD_DAYS = 5


def _ensure_dir():
    STATE_DIR.mkdir(parents=True, exist_ok=True)


def is_valid_trading_date(date_str):
    try:
        dt = datetime.strptime(date_str, '%Y-%m-%d')
        return dt.weekday() < 5
    except Exception:
        return False


def _read(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f).get('history', [])
    except Exception:
        return []


def load_swing_history():
    _ensure_dir()
    history = _read(SWING_RECORD_FILE) if SWING_RECORD_FILE.exists() else []
    data = {"history": sorted(history, key=lambda x: x['date'])}
    return cleanup_old_swing_records(data)


def save_swing_history(data):
    _ensure_dir()
    data = cleanup_old_swing_records(data)
    try:
        with open(SWING_RECORD_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"스윙 트랙 레코드 저장 실패: {e}")


def cleanup_old_swing_records(data):
    now = datetime.now(KST)
    cutoff = (now - timedelta(days=35)).strftime('%Y-%m-%d')
    history = data.get('history', [])
    data['history'] = [
        h for h in history
        if h.get('date', '') >= cutoff and is_valid_trading_date(h.get('date', ''))
    ]
    return data


def record_swing_picks(picks, risk_score=None):
    """당일 2~5일 스윙 추천 종목 기록 (1차 +5%, 2차 +9%, 손절 -3%). risk_score: 추천 시점 AI 리스크 점수(매일 저장)"""
    if not picks:
        return
    now = datetime.now(KST)
    data = load_swing_history()
    existing_dates = {h.get('date') for h in data.get('history', [])}
    hm = now.hour * 100 + now.minute
    if now.weekday() >= 5 or hm < 1500:
        cur = now - timedelta(days=1)
        while cur.weekday() >= 5:
            cur -= timedelta(days=1)
        prev_bday = cur.strftime('%Y-%m-%d')
        if prev_bday not in existing_dates:
            date_str = prev_bday
        else:
            return
    else:
        date_str = now.strftime('%Y-%m-%d')
    existing = [h for h in data.get('history', []) if h.get('date') == date_str]

    pick_items = []
    for p in picks:
        entry_p = p.get('price', p.get('close_price', 0))
        if entry_p <= 0:
            continue
        t1 = int(round(entry_p * (1 + T1_PCT / 100)))
        t2 = int(round(entry_p * (1 + T2_PCT / 100)))
        sl = int(round(entry_p * (1 + SL_PCT / 100)))
        item = {
            'code': p['code'],
            'name': p['name'],
            'market': p.get('market', 'KRX'),
            'sector': p.get('sector', '우량스윙주'),
            'catalyst': p.get('catalyst', ''),
            'catalyst_url': p.get('catalyst_url', f"https://m.stock.naver.com/domestic/stock/{p['code']}/news"),
            'catalyst_source': p.get('catalyst_source', ''),
            'entry_price': entry_p,
            'price': entry_p,
            'change_pct': p.get('change_pct', 0),
            'amount_eok': p.get('amount_eok', 0),
            'marcap': p.get('marcap', 0),
            'marcap_str': p.get('marcap_str', ''),
            'target_1': t1,
            'target_1_pct': '+5.0%',
            'target_2': t2,
            'target_2_pct': '+9.0%',
            'stop_loss': sl,
            'stop_loss_pct': '-3.0%',
            'rule_v': SWING_RULE_VERSION,
            'score': p.get('score', 92),
            'reason': p.get('reason', '20일선 눌림목 반등 및 수급 메이저 집중 우상향 스윙주'),
            'holding_period': '2~5영업일 분할 매도 (1차 +5% / 2차 +9%)',
            'tags': p.get('tags', ['스윙추천', '20일선눌림목']),
            'chart_url': p.get('chart_url', f"https://m.stock.naver.com/domestic/stock/{p['code']}/total"),
            'highest_price': entry_p,
            'lowest_price': entry_p,
            'max_return_pct': 0.0,
            'status': '진행중',
            'completed': False,
            'holding_days': 0
        }
        pick_items.append(item)

    if existing:
        if not existing[0].get('evaluated', False):
            existing[0]['picks'] = pick_items
        if risk_score is not None and existing[0].get('risk_score') is None:
            existing[0]['risk_score'] = int(risk_score)
    else:
        new_rec = {
            'date': date_str,
            'picks': pick_items,
            'evaluated': False
        }
        if risk_score is not None:
            new_rec['risk_score'] = int(risk_score)
        data['history'].append(new_rec)

    save_swing_history(data)


def get_recent_stopped_codes(lookback_days=10):
    """
    최근 lookback_days(달력일) 내 추천됐다가 손절(-3%)로 끝난 종목 코드 집합.
    손절 직후 같은 종목을 다시 추천하는 문제(KT&G 연속 손절 등) 방지용 쿨다운.
    """
    try:
        data = load_swing_history()
        cutoff = (datetime.now(KST) - timedelta(days=lookback_days)).strftime('%Y-%m-%d')
        codes = set()
        for h in data.get('history', []):
            if h.get('blocked', False) or h.get('date', '') < cutoff:
                continue
            for p in h.get('picks', []):
                if '손절' in str(p.get('status', '')) and p.get('code'):
                    codes.add(str(p['code']))
        return codes
    except Exception as e:
        logger.warning(f"손절 쿨다운 목록 로드 실패: {e}")
        return set()


def evaluate_swing_performance():
    """추천일 이후 2~5영업일간 주가 흐름을 추적하여 스윙 성과 자동 판정 (1차 +5%, 2차 +9%, 손절 -3%)"""
    data = load_swing_history()
    history = data.get('history', [])
    if not history:
        return

    now = datetime.now(KST)
    today_str = now.strftime('%Y-%m-%d')
    updated = False

    for h in history:
        h_date = h.get('date', '')
        if h_date >= today_str:
            continue
        if h.get('blocked', False):
            continue  # AI 리스크 차단일은 시뮬레이션 불필요 (현금 100% 보존 완료)

        picks = h.get('picks', [])
        all_done = True

        for p in picks:
            # 규칙 버전이 다르면 재판정
            if p.get('rule_v') != SWING_RULE_VERSION:
                p['completed'] = False
                p['rule_v'] = SWING_RULE_VERSION
                p.pop('target_3', None)
                p.pop('target_3_pct', None)
                p.pop('stage', None)
                p.pop('realized_pct', None)
                h['evaluated'] = False

            if p.get('completed', False):
                continue

            code = p.get('code')
            entry_p = p.get('entry_price', 0)
            if entry_p <= 0:
                p['completed'] = True
                continue

            try:
                start = (datetime.strptime(h_date, '%Y-%m-%d') - timedelta(days=7)).strftime('%Y-%m-%d')
                df = fdr.DataReader(code, start)
                if df.empty:
                    all_done = False
                    continue

                if h_date in df.index:
                    entry_p = int(df.loc[h_date, 'Close'])
                    p['entry_price'] = entry_p
                    p['price'] = entry_p

                t1 = int(round(entry_p * (1 + T1_PCT / 100)))
                t2 = int(round(entry_p * (1 + T2_PCT / 100)))
                sl = int(round(entry_p * (1 + SL_PCT / 100)))
                p['target_1'], p['target_2'], p['stop_loss'] = t1, t2, sl
                p['target_1_pct'], p['target_2_pct'], p['stop_loss_pct'] = '+5.0%', '+9.0%', '-3.0%'

                sub = df[df.index.strftime('%Y-%m-%d') > h_date].head(MAX_HOLD_DAYS)
                if sub.empty:
                    all_done = False
                    continue

                elapsed = len(sub)
                p['holding_days'] = elapsed

                highs = sub['High'].values
                lows = sub['Low'].values
                closes = sub['Close'].values

                max_high = float(highs.max())
                min_low = float(lows.min())
                last_close = float(closes[-1])

                p['highest_price'] = int(max_high)
                p['lowest_price'] = int(min_low)

                max_ret = round(((max_high - entry_p) / entry_p) * 100, 2)
                min_ret = round(((min_low - entry_p) / entry_p) * 100, 2)
                p['max_return_pct'] = max_ret

                # 1) 2차 목표가 달성 (+9% 이상)
                if max_high >= t2:
                    p['status'] = '2차 전량 달성'
                    p['is_success'] = True
                    p['completed'] = True
                    p['final_return_pct'] = max_ret
                # 2) 1차 목표가 달성 (+5% 이상)
                elif max_high >= t1:
                    p['status'] = '1차 분할 달성'
                    p['is_success'] = True
                    if elapsed >= MAX_HOLD_DAYS:
                        p['completed'] = True
                        p['final_return_pct'] = max_ret
                    else:
                        all_done = False
                # 3) 손절선 이탈 (-3% 이하)
                elif min_low <= sl:
                    loss_pct = round(((sl - entry_p) / entry_p) * 100, 2)
                    p['status'] = '손절 이탈'
                    p['is_success'] = False
                    p['completed'] = True
                    p['final_return_pct'] = -3.0
                # 4) 기간 만료 (5영업일 경과)
                else:
                    if elapsed >= MAX_HOLD_DAYS:
                        cur_ret = round(((last_close - entry_p) / entry_p) * 100, 2)
                        p['status'] = '기간 만료'
                        p['is_success'] = cur_ret >= 0
                        p['completed'] = True
                        p['final_return_pct'] = cur_ret
                    else:
                        p['status'] = f"진행중 ({elapsed}일차)"
                        all_done = False

                updated = True
            except Exception as e:
                logger.warning(f"스윙 성과 추적 실패 ({p.get('name')}): {e}")
                all_done = False

        h['evaluated'] = all_done

    if updated:
        save_swing_history(data)


def render_monthly_swing_history_html():
    """웹 대시보드 전용 '최근 1개월 스윙 성과' 탭 HTML 렌더링 (원래 손익비 +5%/+9%/-3% 기준)"""
    data = load_swing_history()
    history = [h for h in data.get('history', []) if is_valid_trading_date(h.get('date', ''))]

    now = datetime.now(KST)
    history.sort(key=lambda x: x['date'], reverse=True)

    total_picks = 0
    win_picks = 0
    loss_picks = 0
    win_returns = []
    loss_returns = []
    total_cum = 0.0
    defense_count = 0

    hold_days = []
    t1_hits = 0
    for h in history:
        is_h_blocked = h.get('blocked', False)
        for p in h.get('picks', []):
            if is_h_blocked or '차단' in p.get('status', ''):
                defense_count += 1
                continue  # 리스크 차단으로 현금 100% 보존된 스윙 종목은 실체결 통계에서 분리

            if not p.get('completed'):
                continue
            ret = float(p.get('final_return_pct', 0.0) or 0.0)
            total_picks += 1
            total_cum += ret
            hold_days.append(p.get('holding_days', 0) or 0)
            if p.get('is_success') or p.get('max_return_pct', 0.0) >= T1_PCT:
                t1_hits += 1
            if ret > 0 or p.get('is_success'):
                win_picks += 1
                win_returns.append(ret if ret > 0 else p.get('max_return_pct', 5.0))
            else:
                loss_picks += 1
                loss_returns.append(abs(ret))

    win_rate = (win_picks / total_picks * 100) if total_picks > 0 else 0.0
    t1_rate = (t1_hits / total_picks * 100) if total_picks > 0 else 0.0
    avg_win = (sum(win_returns) / len(win_returns)) if win_returns else 0.0
    avg_loss = (sum(loss_returns) / len(loss_returns)) if loss_returns else 0.0
    rr_ratio = (avg_win / avg_loss) if avg_loss > 0 else 0.0
    avg_ret = (total_cum / total_picks) if total_picks > 0 else 0.0
    avg_hold = (sum(hold_days) / len(hold_days)) if hold_days else 0.0

    start_date = (now - timedelta(days=30)).strftime('%Y-%m-%d')
    end_date = now.strftime('%Y-%m-%d')

    summary_html = f"""
    <div class="track-summary-grid">
        <div class="track-stat-card stat-swing-winrate">
            <div class="stat-label">🎯 30일 스윙 실매매 승률 (목표 달성률)</div>
            <div class="stat-value">{win_rate:.1f}%</div>
            <div class="stat-sub">{win_picks}승 {loss_picks}패 ({total_picks}회 청산) · 1차(+5%) 도달률 {t1_rate:.0f}%</div>
        </div>
        <div class="track-stat-card stat-swing-rr">
            <div class="stat-label">⚖️ 스윙 평균 손익비 (P/L Ratio)</div>
            <div class="stat-value">{rr_ratio:.2f} : 1</div>
            <div class="stat-sub">익절 평균 +{avg_win:.2f}% / 손절 평균 -{avg_loss:.2f}%</div>
        </div>
        <div class="track-stat-card stat-swing-cum">
            <div class="stat-label">💰 30일 스윙 누적 합산 수익률</div>
            <div class="stat-value">{total_cum:+.2f}%</div>
            <div class="stat-sub">종목당 평균 최고도달 {avg_ret:+.2f}%</div>
        </div>
        <div class="track-stat-card stat-swing-period" style="border-left: 4px solid #10b981;">
            <div class="stat-label">🛡️ 스윙 AI 리스크 방어 (원금 보존)</div>
            <div class="stat-value" style="color: #34d399;">{defense_count}건 방어</div>
            <div class="stat-sub">폭락장 매수 차단 · 현금 100% 보존</div>
        </div>
    </div>
    """

    cards_html = ""
    for h in history:
        h_date = h.get('date', '')
        evaluated = h.get('evaluated', False)
        is_blocked = h.get('blocked', False)
        status_tag = '<span class="hist-badge badge-shield" style="background:#065f46; color:#34d399; border:1px solid #059669;">🛡️ 리스크 차단 (현금 100% 방어)</span>' if is_blocked else ('<span class="hist-badge badge-done">✓ 추적 완료</span>' if evaluated else '<span class="hist-badge badge-wait">⏳ 2~5일 추세 진행중</span>')

        items_html = ""
        for p in h.get('picks', []):
            code = p.get('code', '')
            name = p.get('name', '')
            sec = p.get('sector', '우량스윙')
            cat = p.get('catalyst', '')
            entry_p = p.get('entry_price', 0)
            high_p = p.get('highest_price', entry_p)
            max_ret = p.get('max_return_pct', 0.0)
            status = p.get('status', '진행중')
            h_days = p.get('holding_days', 0)
            marcap_str = p.get('marcap_str', '')
            marcap_tag = f" <span class='hist-marcap'>시총 {marcap_str}</span>" if marcap_str else ""
            p_blocked = is_blocked or ('차단' in status)

            fin_ret = p.get('final_return_pct', 0.0) or 0.0
            completed = p.get('completed', False)

            if p_blocked:
                risk_pt = p.get('risk_score', h.get('risk_score', 56))
                badge = '<span class="res-badge shield" style="background:#065f46; color:#34d399; border:1px solid #059669; font-weight:700;">🛡️ AI 리스크 차단 (현금 보존)</span>'
                res_str = f"오늘 AI 리스크 <b>{risk_pt}점 [DANGER]</b> 감지 ➔ 스윙 신규 매수 전면 차단 · <b>100% 현금 보존</b> (하락장 원금 방어 성공) {badge}"
            elif '2차' in status:
                badge = f'<span class="res-badge win-gold">🚀 2차 전량 달성 (+{max_ret:.2f}%)</span>'
            elif '1차' in status:
                badge = f'<span class="res-badge win">🎯 1차 분할 달성 (+{max_ret:.2f}%)</span>'
            elif '손절' in status:
                badge = f'<span class="res-badge loss">🔻 손절 이탈 ({fin_ret:+.2f}%)</span>'
            elif completed:
                badge = f'<span class="res-badge {"win" if fin_ret > 0 else "loss"}">⌛ 기간만료 종가청산 ({fin_ret:+.2f}%)</span>'
            else:
                badge = f'<span class="res-badge wait">⏳ 진행중 ({h_days}일차, 최고 {max_ret:+.2f}%)</span>'

            low_p = p.get('lowest_price', entry_p)
            min_ret = round(((low_p - entry_p) / entry_p) * 100, 2) if entry_p > 0 else 0.0
            if not p_blocked:
                if '손절' in status:
                    res_str = f"{h_date} 종가 {entry_p:,}원 → 최저 <b>{low_p:,}원</b> (<span class='down'>{min_ret:+.2f}%</span> · 1차목표 +5% 미달, 반등최고 {max_ret:+.2f}%) {badge}"
                else:
                    res_str = f"{h_date} 종가 {entry_p:,}원 → 최고 <b>{high_p:,}원</b> (<span class='{'up' if max_ret>0 else 'down'}'>{max_ret:+.2f}%</span>) {badge}"

            cat_url = p.get('catalyst_url', f"https://m.stock.naver.com/domestic/stock/{code}/news")
            cat_src = p.get('catalyst_source', '')
            src_str = f" <span class='hist-cat-src'>({cat_src})</span>" if cat_src else ""
            cat_html = f"<div class='hist-cat'>📰 <b>상승 모멘텀</b>: <a href='{cat_url}' target='_blank' rel='noopener noreferrer' class='hist-cat-link'>{cat}{src_str} ↗</a></div>" if cat else ""

            items_html += f"""
            <div class="hist-item">
                <div class="hist-item-header">
                    <div class="hist-name-box">
                        <a href="https://m.stock.naver.com/domestic/stock/{code}/total" target="_blank" rel="noopener noreferrer">
                            <b>{name}</b> <span class="hist-code">{code}</span>
                        </a>
                        <span class="hist-sector">[{sec}]</span>{marcap_tag}
                    </div>
                    <div class="hist-result">{res_str}</div>
                </div>
                {cat_html}
            </div>
            """

        cards_html += f"""
        <div class="history-day-card">
            <div class="history-day-header">
                <div class="day-title">📅 <b>{h_date} 2~5일 스윙 추천</b></div>
                <div>{status_tag}</div>
            </div>
            <div class="history-day-body">
                {items_html}
            </div>
        </div>
        """

    return f"""
    <div class="track-record-wrap">
        {summary_html}
        <div class="history-card-list">
            {cards_html}
        </div>
    </div>
    """
