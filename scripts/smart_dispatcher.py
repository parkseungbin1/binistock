"""
BiniStock 스마트 디스패처 (cron-job.org 단일 엔드포인트 연동)
현재 KST 시각에 맞춰 6대 알림 중 해당하는 작업을 전자동 분기 실행합니다.
"""
import argparse
import logging
import os
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))

logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
logger = logging.getLogger(__name__)


def run_py(script_name, args=None):
    cmd = [sys.executable, str(ROOT / script_name)]
    if args:
        cmd.extend(args)
    logger.info(f"실행: {' '.join(cmd)}")
    res = subprocess.run(cmd)
    if res.returncode != 0:
        logger.error(f"{script_name} 실행 실패 (코드 {res.returncode})")
        sys.exit(res.returncode)
    logger.info(f"✓ {script_name} 정상 완료")


def main():
    parser = argparse.ArgumentParser(description="BiniStock 스마트 디스패처")
    parser.add_argument('--action', default='auto',
                        choices=['auto', 'digest_0700', 'morning_735', 'disclosure_0810',
                                 'morning_835', 'midday_1300', 'preclosing_1400', 'closing_1510', 'close_1535', 'night_1940'],
                        help="수동 액션 강제 지정 (기본값: auto - 현재 시각 기준 자동 판별)")
    args = parser.parse_args()

    action = args.action
    now = datetime.now(KST)
    hour = now.hour
    minute = now.minute
    time_str = now.strftime('%H:%M')

    if not action or action == 'auto':
        # 주말(토/일) 자동 스킵 (시장 휴장)
        if now.weekday() >= 5:
            logger.info(f"[{time_str} KST] 주말({now.strftime('%A')})은 주식 시장 휴장이므로 알림 발송을 건너뜁니다.")
            return

        # 시간대별 자동 매핑
        if hour == 6 or (hour == 7 and minute < 15):
            action = 'digest_0700'
        elif hour == 7 and 15 <= minute < 55:
            action = 'morning_735'
        elif (hour == 7 and minute >= 55) or (hour == 8 and minute < 25):
            action = 'disclosure_0810'
        elif hour == 8 and 25 <= minute:
            action = 'morning_835'
        elif hour == 13:
            action = 'midday_1300'
        elif hour == 14 and minute < 45:
            action = 'preclosing_1400'
        elif (hour == 14 and minute >= 45) or (hour == 15 and minute < 28):
            action = 'closing_1510'
        elif (hour == 15 and minute >= 28) or (hour == 16):
            action = 'close_1535'
        elif 19 <= hour <= 21:
            action = 'night_1940'
        else:
            logger.info(f"현재 시각({time_str} KST)은 등록된 정규 발송 시간대가 아닙니다.")
            return

    logger.info(f"[{time_str} KST] 결정된 작업: {action}")

    if action == 'digest_0700':
        # 1. 07:00 날씨 & 주간 경제 캘린더
        run_py('daily_digest.py')

    elif action == 'morning_735':
        # 2. 07:35 [08:00 NXT 개장 전 1차 시초가 매도 가이드] (07:40 전)
        run_py('market_alert.py', ['--mode', 'morning_740', '--force'])

    elif action == 'disclosure_0810':
        # 3. 08:10 DART 실적발표(IR) 및 주요 공시 (있을 때만)
        run_py('disclosure_alert.py', ['--morning'])

    elif action == 'morning_835':
        # 4. 08:35 [09:00 정규장 개장 전 최종 시초가 매도 가이드] (08:40 전)
        run_py('market_alert.py', ['--mode', 'morning_840', '--force'])

    elif action == 'midday_1300':
        # 5. 13:00 [오후장 개시 & 외인/기관 수급 중간점검]
        run_py('market_alert.py', ['--mode', 'midday_1300', '--force'])

    elif action == 'preclosing_1400':
        # 6. 14:00 [15:10 종가베팅 1시간 전 사전 레이더 & 리스크 점검]
        run_py('market_alert.py', ['--mode', 'preclosing_1400', '--force'])

    elif action == 'closing_1510':
        run_py('market_alert.py', ['--mode', 'closing', '--force'])

    elif action == 'close_1535':
        # 15:35 [정규장 최종 마감 시황 & 외인/기관 수급 종합 리포트]
        run_py('market_alert.py', ['--mode', 'close_1535', '--force'])

    elif action == 'night_1940':
        # 6. 19:40 [20:00 NXT 야간 최종 종가베팅 가이드] + 야간 대장주 TOP 3
        run_py('market_alert.py', ['--mode', 'night', '--force'])

    # 텔레그램 발송 완료 후, 항상 웹 대시보드(dist/index.html)를 즉시 실시간 동시 빌드하여 GitHub Pages로 자동 배포
    logger.info("🌐 [웹 대시보드 실시간 동시 빌드] generate_web.py 실행 시작")
    run_py('generate_web.py')
    logger.info("✅ [웹 대시보드 빌드 완료] GitHub Pages 배포 단계로 연동")


if __name__ == '__main__':
    main()
