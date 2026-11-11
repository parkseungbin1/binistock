import json
import logging
import math
import sys
from pathlib import Path
from typing import Any

# news-stock 루트 경로 등록
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

logger = logging.getLogger('KalmanKelly')


class KalmanKellyFilter:
    """
    칼만 필터(Kalman Filter) 기반 동적 승률 및 적응형 켈리(Adaptive Kelly) 자기보정 엔진
    - 상태 변수 (State): 잠재 승률 w_t, 평균 수익률 win_mag, 평균 손실률 loss_mag
    - 노이즈 제거: 불규칙한 단기 손익 노이즈를 필터링하여 전략 본질의 엣지(Edge) 추정
    - 모멘텀 가속 & 드로다운 방어: 최근 연승/연패 추세에 따라 켈리 계수 동적 증감
    - 불확실성(P) 감응형 수축: 표본 수가 적거나 분산이 클 때 자동으로 안전 비중으로 축소
    """

    def __init__(
        self,
        prior_win_rate: float = 0.73,
        prior_p: float = 0.04,
        q_w: float = 0.002,
        r_w: float = 0.07,
    ):
        self.w_hat = float(prior_win_rate)
        self.P_w = float(prior_p)
        self.Q_w = float(q_w)
        self.R_w = float(r_w)

        self.win_mag = 3.50
        self.loss_mag = 1.65
        self.P_wm = 0.50
        self.P_lm = 0.50
        self.Q_m = 0.01
        self.R_m = 0.20

        self.streak = 0
        self.trade_count = 0

    def update(self, is_win: bool, ret_pct: float):
        """단일 매매 결과를 칼만 필터 상태에 반영"""
        self.trade_count += 1
        y = 1.0 if is_win else 0.0

        # 1. 승률 상태 예측 (Predict)
        w_pred = self.w_hat
        P_pred = self.P_w + self.Q_w

        # 2. 칼만 이득(Kalman Gain) 및 승률 갱신 (Update)
        K_w = P_pred / (P_pred + self.R_w)
        self.w_hat = max(0.35, min(0.92, w_pred + K_w * (y - w_pred)))
        self.P_w = max(0.001, (1.0 - K_w) * P_pred)

        # 3. 손익 크기(Magnitude) 갱신
        if is_win and ret_pct > 0:
            P_pred_m = self.P_wm + self.Q_m
            K_m = P_pred_m / (P_pred_m + self.R_m)
            self.win_mag = max(1.0, min(15.0, self.win_mag + K_m * (ret_pct - self.win_mag)))
            self.P_wm = max(0.01, (1.0 - K_m) * P_pred_m)
            self.streak = (self.streak + 1) if self.streak > 0 else 1
        elif not is_win and ret_pct < 0:
            loss_val = abs(ret_pct)
            P_pred_m = self.P_lm + self.Q_m
            K_m = P_pred_m / (P_pred_m + self.R_m)
            self.loss_mag = max(0.5, min(10.0, self.loss_mag + K_m * (loss_val - self.loss_mag)))
            self.P_lm = max(0.01, (1.0 - K_m) * P_pred_m)
            self.streak = (self.streak - 1) if self.streak < 0 else -1

    def get_calibrated_kelly(self, risk_score: int = 36, default_base_pct: float = 24.0) -> dict[str, Any]:
        """칼만 필터 상태를 종합하여 당일 권장 투입률 및 텔레메트리 산출"""
        rr = self.win_mag / max(self.loss_mag, 0.5)
        full_k = self.w_hat - ((1.0 - self.w_hat) / max(rr, 0.5))
        rr = self.win_mag / max(self.loss_mag, 0.5)
        full_k = self.w_hat - ((1.0 - self.w_hat) / max(rr, 0.5))
        portfolio_k = max(0.45, full_k * 1.45)

        # 모멘텀 승수 계산
        if self.streak >= 3:
            mom = min(1.18, 1.0 + (self.streak * 0.035))
            mom_label = f"🔥 연승 모멘텀 가속 (+{int(round((mom - 1.0) * 100))}%)"
        elif self.streak <= -2:
            mom = max(0.65, 1.0 - (abs(self.streak) * 0.08))
            mom_label = f"🛡️ 드로다운 방어 감속 (-{int(round((1.0 - mom) * 100))}%)"
        else:
            mom = 1.0
            mom_label = "⚖️ 정상 중립 모드"

        unc_factor = max(0.85, 1.0 - math.sqrt(self.P_w))

        if risk_score > 65:
            calibrated_pct = 0.0
            risk_label = f"🚨 AI 리스크 {risk_score}점 초과로 전면 매수 차단 (현금 100% 보존)"
            is_active = False
        else:
            risk_factor = max(0.45, 1.0 - (risk_score / 130.0))
            raw_calibrated = portfolio_k * mom * unc_factor * risk_factor * 100.0
            calibrated_pct = round(max(30.0, min(72.0, raw_calibrated)), 1)
            risk_label = f"✅ AI 리스크 {risk_score}점 정상 반영"
            is_active = True

        return {
            'calibrated_pct': calibrated_pct,
            'default_base_pct': default_base_pct,
            'is_active': is_active,
            'filtered_win_rate': round(self.w_hat * 100.0, 1),
            'filtered_rr_ratio': round(rr, 2),
            'filtered_win_mag': round(self.win_mag, 2),
            'filtered_loss_mag': round(self.loss_mag, 2),
            'uncertainty_p': round(self.P_w, 5),
            'streak': self.streak,
            'momentum_mult': round(mom, 2),
            'momentum_label': mom_label,
            'risk_score': risk_score,
            'risk_label': risk_label,
            'trade_count': self.trade_count,
        }


def load_trade_records() -> list[dict]:
    """종가베팅 및 스윙 트랙레코드 수집"""
    trades = []
    base_data_dir = _ROOT / 'data'

    # 종가베팅 트랙레코드
    b_file = base_data_dir / 'betting_track_record.json'
    if b_file.exists():
        try:
            with open(b_file, 'r', encoding='utf-8') as f:
                b_data = json.load(f)
                for h in b_data.get('history', []):
                    for p in h.get('picks', []):
                        if 'gap_pct' in p:
                            gap = float(p['gap_pct'])
                            is_win = bool(p.get('is_success', gap > 0))
                            max_p = float(p.get('max_profit_pct', gap))
                            ret_val = max(gap, max_p, 1.5) if is_win else min(gap, -0.5)
                            trades.append({
                                'date': h.get('date', ''),
                                'ret_pct': ret_val,
                                'is_win': is_win,
                                'source': 'BETTING_RECORD'
                            })
        except Exception as e:
            logger.warning(f"종가베팅 트랙레코드 파싱 실패: {e}")

    trades.sort(key=lambda x: x.get('date', ''))
    return trades


def calibrate_kelly_with_kalman(
    base_invest_pct: float = 24.0,
    risk_score: int = 36
) -> dict[str, Any]:
    kf = KalmanKellyFilter(prior_win_rate=0.73, prior_p=0.04)
    trades = load_trade_records()

    if trades:
        for t in trades:
            kf.update(t['is_win'], t['ret_pct'])

    return kf.get_calibrated_kelly(risk_score=risk_score, default_base_pct=base_invest_pct)

