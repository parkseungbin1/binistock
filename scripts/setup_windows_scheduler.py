"""
Windows 작업 스케줄러 등록 스크립트
깃허브 액션의 무료 서버 대기열 지연(1~2시간)을 완전히 해결하여
내 컴퓨터에서 정확한 시각에 1초의 오차도 없이 텔레그램을 발송합니다.
"""
import sys
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYTHON = sys.executable

TASKS = [
    {
        "name": "BiniStock_01_Morning_0700_Digest",
        "time": "07:00",
        "freq": "DAILY",
        "script": "daily_digest.py",
        "args": "",
        "desc": "07:00 서울 날씨 + 이번주 주요 경제 캘린더"
    },
    {
        "name": "BiniStock_02_NxtPreMarket_0735",
        "time": "07:35",
        "freq": "WEEKLY",
        "days": "MON,TUE,WED,THU,FRI",
        "script": "market_alert.py",
        "args": "--mode morning_740 --force",
        "desc": "07:35 [08:00 NXT 개장 전 시초가 매도 가이드] (07:40 전 1차 알림)"
    },
    {
        "name": "BiniStock_03_Disclosure_0810",
        "time": "08:10",
        "freq": "WEEKLY",
        "days": "MON,TUE,WED,THU,FRI",
        "script": "disclosure_alert.py",
        "args": "--morning",
        "desc": "08:10 DART 장전 실적발표(IR) 및 공시 (있을 때만)"
    },
    {
        "name": "BiniStock_04_KrxPreMarket_0835",
        "time": "08:35",
        "freq": "WEEKLY",
        "days": "MON,TUE,WED,THU,FRI",
        "script": "market_alert.py",
        "args": "--mode morning_840 --force",
        "desc": "08:35 [09:00 정규장 개장 전 최종 매도 가이드] (08:40 전 2차 알림)"
    },
    {
        "name": "BiniStock_05_ClosingBetting_1510",
        "time": "15:10",
        "freq": "WEEKLY",
        "days": "MON,TUE,WED,THU,FRI",
        "script": "market_alert.py",
        "args": "--mode closing --force",
        "desc": "15:10 [15:30 정규장 1차 종가베팅 가이드] + AI 종가베팅 주도주 TOP 3"
    },
    {
        "name": "BiniStock_06_NxtNight_1940",
        "time": "19:40",
        "freq": "WEEKLY",
        "days": "MON,TUE,WED,THU,FRI",
        "script": "market_alert.py",
        "args": "--mode night --force",
        "desc": "19:40 [20:00 NXT 야간 최종 종가베팅 가이드] + 야간 주도 대장주 TOP 3"
    }
]

def main():
    print("=" * 60)
    print("BiniStock Windows 정밀 스케줄러 자동 등록")
    print(f"Python: {PYTHON}")
    print(f"경로: {ROOT}")
    print("=" * 60)

    for t in TASKS:
        name = t["name"]
        time_str = t["time"]
        script_path = str(ROOT / t["script"])
        cmd = f'"{PYTHON}" "{script_path}" {t["args"]}'.strip()

        # Delete old task if exists
        subprocess.run(["schtasks", "/Delete", "/TN", name, "/F"], capture_output=True)

        # Create task
        args = ["schtasks", "/Create", "/TN", name, "/TR", cmd, "/SC", t["freq"], "/ST", time_str, "/F"]
        if t["freq"] == "WEEKLY" and "days" in t:
            args.extend(["/D", t["days"]])

        res = subprocess.run(args, capture_output=True, text=True)
        if res.returncode == 0:
            print(f"[OK] [{time_str}] {t['desc']}")
        else:
            print(f"[FAIL] ({name}): {res.stderr.strip()}")

    print("=" * 60)
    print("완료! 이제 매일 아침 정해진 시간에 1초의 지연도 없이 발송됩니다.")

if __name__ == '__main__':
    main()
