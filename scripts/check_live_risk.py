"""
BiniStock 초고속 실시간 시장 리스크 & 15:10 종가베팅 즉시 진단 스크립트
PC에서 실행 시 약 2~3초 만에 나스닥 선물, 반도체 지수, 환율, 수급, AI 리스크 스코어를 실시간 조회합니다.
"""
import json
import sys
import webbrowser
from datetime import datetime, timezone, timedelta
from pathlib import Path

# 콘솔 UTF-8 인코딩 설정 (Windows 이모지 출력 깨짐 방지)
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.market_score import (
    fetch_nasdaq_futures,
    fetch_naver_index,
    fetch_usdkrw,
    fetch_cnn_fear_greed,
    fetch_kr_market,
    fetch_vix,
    fetch_us10y,
)
from src.risk_score import compute_risk_score, get_risk_assessment

KST = timezone(timedelta(hours=9))


def run_check():
    now = datetime.now(KST)
    print("=" * 66)
    print("  🚀 [BiniStock] AI 실시간 시장 리스크 & 15:10 종가베팅 실시간 진단")
    print(f"  ⏰ 조회 시각: {now.strftime('%Y-%m-%d %H:%M:%S')} KST")
    print("=" * 66)
    print("  ⚡ 실시간 글로벌 금융 지표 및 국내 증시 데이터 수집 중...")

    # 1. 글로벌/국내 시황 지표 수집
    fut_price, fut_ratio = fetch_nasdaq_futures()
    sox_close, sox_ratio = fetch_naver_index('.SOX')
    fx_close, fx_ratio, fx_diff = fetch_usdkrw()
    cnn_score, cnn_rating = fetch_cnn_fear_greed()
    vix_close, vix_ratio = fetch_vix()
    us10y_price, us10y_diff = fetch_us10y()

    kp_close, kp_ratio, kp_for, kp_inst, kp_for_num, kp_inst_num = fetch_kr_market('KOSPI')
    kd_close, kd_ratio, kd_for, kd_inst, kd_for_num, kd_inst_num = fetch_kr_market('KOSDAQ')

    # 2. AI 리스크 스코어 계산
    vix_val = float(str(vix_close).replace(',', '')) if vix_close else 20.0
    risk_ctx = {
        'fut_ratio': fut_ratio or 0.0,
        'sox_ratio': sox_ratio or 0.0,
        'kp_ratio': kp_ratio or 0.0,
        'kd_ratio': kd_ratio or 0.0,
        'fx_ratio': fx_ratio or 0.0,
        'cnn_score': cnn_score or 50.0,
        'vix': vix_val,
        'us10y': us10y_diff or 0.0,
    }
    score = compute_risk_score(risk_ctx)
    assessment = get_risk_assessment(score)

    grade = assessment['grade']
    desc = assessment['desc']

    # 3. 콘솔 브리핑 출력
    print("\n" + "─" * 66)
    print(f"  🎯 [AI 실시간 복합 시장 리스크 스코어] : {score}점 / 100점")
    print(f"  📊 위험 등급 : [{grade}]")
    print(f"  💡 행동 지침 : {desc}")
    print("─" * 66)

    def fmt_pct(val):
        if val is None:
            return "N/A"
        return f"{val:+.2f}%"

    print("  [7대 핵심 선행 및 수급 지표]")
    print(f"  1. 미국 E-mini 나스닥100 선물 : {fmt_pct(fut_ratio)} (현재가: {fut_price or 'N/A'})")
    print(f"  2. 필라델피아 반도체 지수(SOX): {fmt_pct(sox_ratio)} ({sox_close or 'N/A'})")
    print(f"  3. 코스피(KOSPI)              : {fmt_pct(kp_ratio)} ({kp_close}) | 외인 {kp_for} / 기관 {kp_inst}")
    print(f"  4. 코스닥(KOSDAQ)             : {fmt_pct(kd_ratio)} ({kd_close}) | 외인 {kd_for} / 기관 {kd_inst}")
    print(f"  5. 원/달러 환율               : {fx_close}원 ({fmt_pct(fx_ratio)})")
    print(f"  6. 미국 VIX 변동성 / 국채10년 : VIX {vix_close} / 국채 10년물 {fmt_pct(us10y_diff)}")
    print(f"  7. CNN 공포·탐욕 지수         : {cnn_score}점 ({cnn_rating})")
    print("─" * 66)

    # 4. 종가베팅 추천주 현황 (betting_track_record.json)
    rec_file = ROOT / "data" / "betting_track_record.json"
    if rec_file.exists():
        try:
            with open(rec_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            history = data.get("history", [])
            if history:
                latest = history[-1]
                picks = latest.get("picks", [])
                date_str = latest.get("date", "")
                print(f"  📌 [최신 등록된 종가베팅 주도주 ({date_str})]")
                for idx, p in enumerate(picks, 1):
                    code = p.get("code", "")
                    name = p.get("name", "")
                    close_p = p.get("close_price", 0)
                    reason = p.get("reason", "")
                    print(f"    [{idx}] {name} ({code}) : 기준가 {close_p:,}원 | {reason}")
                print("─" * 66)
        except Exception as e:
            print(f"  ⚠️ 최신 종가베팅 주도주 조회 실패: {e}")

    print("  [조회 옵션 안내]")
    print("  * 온라인 실시간 웹 대시보드 : https://parkseungbin1.github.io/binistock/")
    dist_html = ROOT / "dist" / "index.html"
    if dist_html.exists():
        print("  * 로컬 대시보드 파일 : dist\\index.html")
    print("=" * 66)


if __name__ == '__main__':
    try:
        run_check()
    except Exception as e:
        print(f"\n❌ 조회 중 오류 발생: {e}")

    print("\n[Enter] 키를 누르면 웹 브라우저로 대시보드를 엽니다 (창을 닫으려면 아무 키나 누르세요)...")
    try:
        user_in = input()
        dist_file = ROOT / "dist" / "index.html"
        if dist_file.exists():
            webbrowser.open(dist_file.as_uri())
        else:
            webbrowser.open("https://parkseungbin1.github.io/binistock/")
    except Exception:
        pass
