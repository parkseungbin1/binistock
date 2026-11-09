"""
종가베팅 & 시초가 매도 타이밍 전문 시황 알림 텔레그램 발송 스크립트
1. [아침 07:40] 🌅 08:00 NXT 프리마켓 개장 전 시초가 매도 가이드
2. [아침 08:40] 🌅 09:00 정규장 개장 전 최종 매도 가이드
3. [오후 15:10] 🎯 15:30 정규장 마감 1차 종가베팅 가이드
4. [저녁 19:40] 🎯 20:00 NXT 8시 마감 최종 종가베팅 가이드
"""
import argparse
import logging
import os
import sys
from pathlib import Path

# Windows 콘솔 출력 시 이모지 인코딩 오류 방지
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
from src.market_score import get_market_score_message
from src.telegram_sender import send_economic_calendar_to_telegram_sync


def main():
    parser = argparse.ArgumentParser(description="종가베팅 & 시초가 매도 시황 알림 발송")
    parser.add_argument(
        '--mode',
        choices=['morning_740', 'morning_840', 'morning', 'midday_1300', 'preclosing_1400', 'closing', 'close_1535', 'night', 'auto'],
        default='auto',
        help="발송 모드 지정 (기본값: auto - 현재 KST 시간 자동 판별)"
    )
    parser.add_argument(
        '--force',
        action='store_true',
        help="만료 시간 가드를 무시하고 강제 발송 (수동 테스트용)"
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    load_dotenv()

    token = os.getenv('TELEGRAM_BOT_TOKEN')
    chat_id = os.getenv('TELEGRAM_CHAT_ID')
    if not (token and chat_id):
        print("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID가 설정되지 않았습니다.")
        sys.exit(1)

    # [만료 가드] 서버 지연으로 이미 장이 개장/마감된 이후 늦게 켜졌다면 발송 취소 (뒷북 알림 방지)
    if not args.force:
        from datetime import datetime, timezone, timedelta
        kst = timezone(timedelta(hours=9))
        now = datetime.now(kst)
        time_str = now.strftime('%H:%M')

        if args.mode in ('morning_740', 'morning') and (now.hour > 8 or (now.hour == 8 and now.minute > 5)):
            print(f"⚠️ [발송 건너뜀] 현재 시각({time_str} KST)은 08:00 NXT 개장 이후입니다. 지연 실행된 07:40 가이드 발송을 취소합니다.")
            return

        if args.mode == 'morning_840' and (now.hour > 9 or (now.hour == 9 and now.minute > 5)):
            print(f"⚠️ [발송 건너뜀] 현재 시각({time_str} KST)은 09:00 정규장 개장 이후입니다. 지연 실행된 08:40 가이드 발송을 취소합니다.")
            return

        if args.mode == 'midday_1300' and (now.hour > 13 or (now.hour == 13 and now.minute > 45)):
            print(f"⚠️ [발송 건너뜀] 현재 시각({time_str} KST)은 13:00 오후장 개시 이후 한참 지연되었습니다. 발송을 취소합니다.")
            return

        if args.mode == 'preclosing_1400' and (now.hour > 14 or (now.hour == 14 and now.minute > 45)):
            print(f"⚠️ [발송 건너뜀] 현재 시각({time_str} KST)은 14:00 이후 지연되었습니다. 곧 15:10 종가베팅 알림이 실행되므로 취소합니다.")
            return

        if args.mode == 'closing' and (now.hour > 15 or (now.hour == 15 and now.minute > 35)):
            print(f"⚠️ [발송 건너뜀] 현재 시각({time_str} KST)은 15:30 정규장 마감 이후입니다. 지연 실행된 15:10 가이드 발송을 취소합니다.")
            return

        if args.mode == 'close_1535' and (now.hour > 17 or now.hour < 15):
            print(f"⚠️ [발송 건너뜀] 현재 시각({time_str} KST)은 15:35 정규장 마감 시간대를 벗어났습니다. 발송을 취소합니다.")
            return

        if args.mode == 'night' and (now.hour > 20 or (now.hour == 20 and now.minute > 5)):
            print(f"⚠️ [발송 건너뜀] 현재 시각({time_str} KST)은 20:00 NXT 마감 이후입니다. 지연 실행된 19:40 가이드 발송을 취소합니다.")
            return

    print(f"시황 가이드 생성 중... (모드: {args.mode})")
    msg = get_market_score_message(mode=args.mode)
    print("-" * 40)
    print(msg)
    print("-" * 40)

    print("텔레그램 전송 중...")
    ok = send_economic_calendar_to_telegram_sync(msg, token, chat_id)
    if ok:
        print("✓ 시황 알림 전송 성공!")
    else:
        print("✗ 시황 알림 전송 실패")
        sys.exit(1)


if __name__ == '__main__':
    main()
