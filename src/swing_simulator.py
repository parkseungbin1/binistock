"""
Swing Simulator 모듈 (What‑If 엔진)
스윙 추천 종목을 기반으로 사용자가 목표 비율(+3%, +5%, +10%) 및 손절 비율(-2%, -3%)을 시뮬레이션할 수 있습니다.
100% 무료 순수 파이썬 + 클라이언트 사이드 실시간 인터랙션 지원.
"""

def simulate_profit(entry_price: int, target_pct: float, stop_loss_pct: float = -2.0) -> dict:
    """단일 시뮬레이션 결과 반환"""
    if not entry_price or entry_price <= 0:
        return {"target_price": 0, "stop_price": 0, "profit_pct": target_pct, "loss_pct": stop_loss_pct}
    target_price = int(round(entry_price * (1 + target_pct / 100)))
    stop_price = int(round(entry_price * (1 + stop_loss_pct / 100)))
    return {
        "target_price": target_price,
        "stop_price": stop_price,
        "profit_pct": target_pct,
        "loss_pct": stop_loss_pct,
        "gain_amount": target_price - entry_price,
        "risk_amount": entry_price - stop_price
    }

def render_swing_simulator_card(picks: list) -> str:
    """대시보드에 내장될 스윙 What-If 시뮬레이터 UI HTML"""
    if not picks:
        return ""
    
    rows = []
    for p in picks:
        code = p.get('code', '')
        name = p.get('name', '종목')
        price = p.get('price') or p.get('close_price') or 0
        if price <= 0:
            continue
        
        sim1 = simulate_profit(price, 3.0, -2.0)
        sim2 = simulate_profit(price, 5.0, -2.0)
        sim3 = simulate_profit(price, 9.0, -3.0)
        
        rows.append(f"""
        <tr class="sim-row" data-code="{code}" data-price="{price}">
            <td class="sim-stock-cell">
                <b>{name}</b> <span class="sim-code">{code}</span>
            </td>
            <td class="sim-price-cell">{price:,}원</td>
            <td class="sim-t1">
                <span class="sim-val">{sim1['target_price']:,}원</span>
                <span class="sim-pct badge-green">+3.0%</span>
            </td>
            <td class="sim-t2">
                <span class="sim-val">{sim2['target_price']:,}원</span>
                <span class="sim-pct badge-green">+5.0%</span>
            </td>
            <td class="sim-t3">
                <span class="sim-val">{sim3['target_price']:,}원</span>
                <span class="sim-pct badge-gold">+9.0%</span>
            </td>
            <td class="sim-stop">
                <span class="sim-val">{sim3['stop_price']:,}원</span>
                <span class="sim-pct badge-blue">-3.0%</span>
            </td>
            <td class="sim-kelly-cell" data-price="{price}">
                <span class="kelly-shares-badge">계산중...</span>
            </td>
        </tr>
        """)
    
    if not rows:
        return ""
        
    return f"""
    <div class="swing-sim-card">
        <div class="swing-sim-header">
            <div>
                <h3>🎯 스윙 What-If 목표 수익 시뮬레이터</h3>
                <p class="sim-desc">발굴된 스윙 주도주의 1차(+3%), 2차(+5%), 3차(+9%) 목표 도달가 및 손절 기준선 실시간 산출표</p>
            </div>
            <div class="sim-badge">무료 실시간 연산</div>
        </div>
        <div class="table-responsive">
            <table class="sim-table">
                <thead>
                    <tr>
                        <th>종목명/코드</th>
                        <th>진입 기준가</th>
                        <th>1차 목표 (+3%)</th>
                        <th>2차 목표 (+5%)</th>
                        <th>3차 목표 (+9%)</th>
                        <th>기준 손절가 (-3% · 1차 후 본절)</th>
                        <th>권장 매수량 & 예상 손익 (시드 연동)</th>
                    </tr>
                </thead>
                <tbody>
                    {''.join(rows)}
                </tbody>
            </table>
        </div>
    </div>
    """
