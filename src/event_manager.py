"""
BiniStock 주요일정 & 이벤트 인텔리전스 엔진 (src/event_manager.py)
- 글로벌/국내 거시경제 지표 수집 (ForexFactory + 네이버 증권)
- 파생상품 만기일(옵션만기/네 마녀의 날) 수학적 D-Day 알고리즘
- 한국은행 금통위 및 MSCI 리밸런싱 연간 일정 추적
- DART 자사주 소각 공시 분석 (시총 대비 소각 비중 % 정밀 산출)
- 야간 오버나잇 악재 방패(Risk Guard) & 호재 모멘텀 창(Catalyst Booster) 양방향 판정
"""
import os
import json
import html
import logging
from datetime import datetime, date, timedelta, timezone

logger = logging.getLogger(__name__)
KST = timezone(timedelta(hours=9))


def get_current_kst():
    return datetime.now(KST)


# ---------------------------------------------------------------------------
# 1. 파생상품 만기일 수학적 알고리즘
# ---------------------------------------------------------------------------
def get_nth_weekday_of_month(year: int, month: int, weekday: int, n: int) -> date:
    """특정 연/월의 n번째 특정 요일(0=월, 3=목, 4=금 등) 날짜 반환"""
    first_day = date(year, month, 1)
    day_offset = (weekday - first_day.weekday()) % 7
    first_target = first_day + timedelta(days=day_offset)
    return first_target + timedelta(weeks=n - 1)


def get_next_derivatives_expiry(ref_date: date = None) -> dict:
    """
    국내/미국 파생상품 만기일 및 D-Day 자동 산출
    - 국내 옵션만기일: 매월 2번째 목요일
    - 국내 네 마녀의 날(선물·옵션 동시만기일): 3, 6, 9, 12월 2번째 목요일
    - 미국 쿼드러플 위칭데이: 3, 6, 9, 12월 3번째 금요일
    """
    if ref_date is None:
        ref_date = get_current_kst().date()

    candidates = []
    # 향후 4개월 탐색
    cur_y = ref_date.year
    cur_m = ref_date.month

    for offset in range(0, 4):
        target_m = cur_m + offset
        target_y = cur_y
        while target_m > 12:
            target_m -= 12
            target_y += 1

        # 국내 매월 2번째 목요일 (weekday=3)
        kr_opt = get_nth_weekday_of_month(target_y, target_m, 3, 2)
        is_kr_quad = target_m in (3, 6, 9, 12)

        # 미국 매월 3번째 금요일 (weekday=4)
        us_witch = get_nth_weekday_of_month(target_y, target_m, 4, 3)
        is_us_quad = target_m in (3, 6, 9, 12)

        if kr_opt >= ref_date:
            candidates.append({
                "type": "KR_QUADRUPLE" if is_kr_quad else "KR_OPTION",
                "name": "국내 선물·옵션 동시만기일 (네 마녀의 날)" if is_kr_quad else "국내 옵션만기일",
                "date": kr_opt.strftime("%Y-%m-%d"),
                "d_day": (kr_opt - ref_date).days,
                "is_quadruple": is_kr_quad,
                "country": "한국"
            })

        if us_witch >= ref_date:
            candidates.append({
                "type": "US_QUADRUPLE" if is_us_quad else "US_OPTION",
                "name": "미국 선물·옵션 동시만기일" if is_us_quad else "미국 옵션만기일",
                "date": us_witch.strftime("%Y-%m-%d"),
                "d_day": (us_witch - ref_date).days,
                "is_quadruple": is_us_quad,
                "country": "미국"
            })

    candidates.sort(key=lambda x: (x["d_day"], 0 if x["country"] == "한국" else 1))

    # 가장 가까운 국내 만기일
    next_kr = next((c for c in candidates if c["country"] == "한국"), None)
    # 가장 가까운 동시만기일(네 마녀의 날)
    next_quad = next((c for c in candidates if c["is_quadruple"] and c["country"] == "한국"), None)

    return {
        "next_kr": next_kr,
        "next_quadruple": next_quad,
        "all_upcoming": candidates[:4]
    }


# ---------------------------------------------------------------------------
# 2. 글로벌 마스터 캘린더 (금통위, MSCI, 전시회) 로딩
# ---------------------------------------------------------------------------
def load_global_master_events(ref_date: date = None) -> list:
    """data/global_event_master.json에서 향후 45일 이내 예정된 핵심 이벤트 조회"""
    if ref_date is None:
        ref_date = get_current_kst().date()

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    master_path = os.path.join(base_dir, "data", "global_event_master.json")

    if not os.path.exists(master_path):
        return []

    try:
        with open(master_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        logger.warning(f"global_event_master.json 로딩 실패: {e}")
        return []

    events = []

    # 1) 한국은행 금통위
    for m in data.get("bok_mpc_meetings", []):
        try:
            m_date = datetime.strptime(m["date"], "%Y-%m-%d").date()
            d_diff = (m_date - ref_date).days
            if 0 <= d_diff <= 45:
                events.append({
                    "category": "BOK_RATE",
                    "title": m["name"],
                    "date": m["date"],
                    "d_day": d_diff,
                    "impact": "HIGH",
                    "is_catalyst": False,
                    "is_risk": True,
                    "sectors": ["금융", "증권", "건설"]
                })
        except Exception:
            continue

    # 2) MSCI 리밸런싱
    for r in data.get("msci_rebalancing", []):
        try:
            eff_date = datetime.strptime(r["effective"], "%Y-%m-%d").date()
            d_diff = (eff_date - ref_date).days
            if 0 <= d_diff <= 45:
                events.append({
                    "category": "MSCI_REBALANCING",
                    "title": r["name"],
                    "date": r["effective"],
                    "d_day": d_diff,
                    "impact": "ULTRA_HIGH",
                    "is_catalyst": True,
                    "is_risk": False,
                    "sectors": ["대형주", "패시브수혜주"]
                })
        except Exception:
            continue

    # 3) 글로벌 박람회 / 컨퍼런스 (연중 월별 매핑)
    cur_year = ref_date.year
    for expo in data.get("global_industry_expos", []):
        approx_days = expo.get("approx_days", "")
        if "~" in approx_days:
            start_str = approx_days.split("~")[0].strip()  # 예: "01-06"
            try:
                expo_month, expo_day = map(int, start_str.split("-"))
                # 연도 결정 (현재 월 기준 지난 경우 다음 연도)
                expo_year = cur_year if expo_month >= ref_date.month else cur_year + 1
                expo_date = date(expo_year, expo_month, expo_day)
                d_diff = (expo_date - ref_date).days
                if 0 <= d_diff <= 45:
                    events.append({
                        "category": "EXPO_CONFERENCE",
                        "title": expo["name"],
                        "date": expo_date.strftime("%Y-%m-%d"),
                        "d_day": d_diff,
                        "impact": expo.get("impact", "HIGH"),
                        "is_catalyst": True,
                        "is_risk": False if expo.get("impact") != "WATCH" else True,
                        "sectors": expo.get("sectors", []),
                        "description": expo.get("description", "")
                    })
            except Exception:
                continue

    events.sort(key=lambda x: x["d_day"])
    return events


# ---------------------------------------------------------------------------
# 3. DART 자사주 소각 공시 분석 (시총 대비 소각 비중 % 정밀 산출)
# ---------------------------------------------------------------------------
def extract_burn_catalysts(ref_date: date = None) -> list:
    """
    최신 공시 캐시에서 자사주 소각 결정을 분석하여 시총 대비 비중과 D-Day 산출
    """
    if ref_date is None:
        ref_date = get_current_kst().date()

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cache_path = os.path.join(base_dir, "data", "web_disclosure_cache.json")

    burn_catalysts = []
    if not os.path.exists(cache_path):
        return burn_catalysts

    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            cache = json.load(f)
    except Exception:
        return burn_catalysts

    # buyback_cards에 저장된 소각 공시 HTML 역파싱 또는 최근 소각 공시 탐색
    for card_html in cache.get("buyback_cards", []):
        if "주식소각" not in card_html and "주식 소각" not in card_html:
            continue

        try:
            # 회사명 및 소각 비중 추출
            corp_name = ""
            if "<b>" in card_html and "</b>" in card_html:
                parts = card_html.split("<b>")
                for p in parts[1:]:
                    val = p.split("</b>")[0].strip()
                    if "<a" in val and ">" in val:
                        corp_name = val.split(">")[1].split("<")[0].strip()
                        break
                    elif val and "소각" not in val and "🔥" not in val:
                        corp_name = val
                        break

            # 시총 대비 소각 비중 % 추출
            ratio_pct = 0.0
            if "시가총액의" in card_html and "%" in card_html:
                sub = card_html.split("시가총액의")[1].split("%")[0]
                # 태그 제거
                sub = sub.replace("<b>", "").replace("</b>", "").strip()
                ratio_pct = float(sub)

            # 소각예정일 추출
            burn_date_str = ""
            burn_d_day = None
            if "소각예정일:" in card_html:
                d_part = card_html.split("소각예정일:")[1].split("|")[0].strip()
                burn_date_str = d_part.replace(".", "-")
                try:
                    b_date = datetime.strptime(burn_date_str, "%Y-%m-%d").date()
                    burn_d_day = (b_date - ref_date).days
                except Exception:
                    pass

            corp_name = html.unescape(corp_name).strip() if corp_name else ""
            if corp_name and 0 < ratio_pct <= 50.0:  # 50% 초과는 무상감자/합병 등 이상치 배제
                # 점수 가산점 환산: 7% 이상(+10점), 5% 이상(+7점), 3% 이상(+4점)
                boost = 10 if ratio_pct >= 7.0 else (7 if ratio_pct >= 5.0 else (4 if ratio_pct >= 3.0 else 0))
                burn_catalysts.append({
                    "corp_name": corp_name,
                    "ratio_pct": ratio_pct,
                    "burn_date": burn_date_str,
                    "d_day": burn_d_day,
                    "boost_score": boost,
                    "tag": f"🔥 시총 {ratio_pct:.2f}% 소각 예정 (D-{burn_d_day if burn_d_day is not None else '?'})"
                })
        except Exception as e:
            logger.debug(f"소각 공시 카드 파싱 예외: {e}")

    # 종목명 기준 중복 제거 (최고 소각 비중 기준 단일화)
    dedup = {}
    for bc in burn_catalysts:
        cname = bc["corp_name"]
        if cname not in dedup or bc["ratio_pct"] > dedup[cname]["ratio_pct"]:
            dedup[cname] = bc

    sorted_burns = sorted(dedup.values(), key=lambda x: (x["boost_score"], x["ratio_pct"]), reverse=True)
    return sorted_burns


# ---------------------------------------------------------------------------
# 4. 야간 거시경제 일정 수집 및 오버나잇 리스크 지수 산출 (Risk Guard — 슬림 정밀판)
# ---------------------------------------------------------------------------
# - RED (80점, 매수 전면 차단 · 월 2~3일): 미국 4대 폭탄(FOMC, CPI, Core PCE, 비농업고용 NFP)
# - YELLOW (50점, 비중 50% 축소): 한국은행 금통위, 미국 GDP, 네 마녀의 날(D-0)
# - GREEN (<50점, 정상 매매 · 정보 참고용): 일반 PMI/ISM, 실업률, GTC 등
HIGH_IMPACT_MACRO_KEYWORDS = [
    # [RED 80점: 미국 4대 거시 폭탄]
    (("fomc", "연준 금리", "연방공개시장위원회", "fed interest rate"), 80, "미국 연준 FOMC 기준금리 결정 / 기자회견", True),
    (("cpi", "소비자물가지수", "소비자물가"), 80, "미국 소비자물가지수(CPI) 발표", True),
    (("pce", "소비지출물가지수", "개인소비지출"), 80, "미국 개인소비지출(PCE) 물가지수 발표", True),
    (("non-farm", "nonfarm", "비농업고용", "비농업 부문"), 80, "미국 비농업고용지수(NFP) 발표", True),
    # [YELLOW 50점: 비중 50% 축소 주의 지표]
    (("한국 금리 결정", "기준금리", "금통위"), 50, "한국은행 금통위 기준금리 결정", False),
    (("gdp", "국내총생산"), 50, "미국 GDP(국내총생산) 발표", True),
    # [GREEN 참고용: 정상 매매 유지 (50점 미만)]
    (("unemployment rate", "실업률"), 20, "실업률 발표", True),
    (("ism", "구매관리자지수", "pmi"), 15, "구매관리자지수(PMI/ISM) 발표", True),
    (("gtc",), 10, "엔비디아 GTC (변동성 참고)", False),
]


def evaluate_overnight_event_risk(ref_datetime: datetime = None) -> dict:
    """
    오늘 밤(당일 15:30 ~ 익일 10:30 KST) 또는 주말(금~월)에 터질 거시경제 폭탄 일정 평가
    - Returns:
      - score: 0~100 (높을수록 초고위험)
      - level: GREEN (<50), YELLOW (50~79), RED (>=80)
      - recommendation: 'NORMAL_BETTING', 'HALF_BETTING', 'BLOCK_BETTING'
      - detected_events: 감지된 지표 목록
    """
    if ref_datetime is None:
        ref_datetime = get_current_kst()

    cur_date = ref_datetime.date()
    cur_weekday = ref_datetime.weekday()  # 0=월 ... 4=금, 5=토, 6=일
    is_friday = (cur_weekday == 4)

    # ForexFactory 및 네이버 경제지표 크롤러 호출
    macro_events = []
    try:
        try:
            from src.crawler import EconomicCalendarCrawler
        except ImportError:
            from crawler import EconomicCalendarCrawler
        crawler = EconomicCalendarCrawler()
        raw_events = crawler.get_economic_calendar_data()
        macro_events = raw_events or []
    except Exception as e:
        logger.warning(f"경제지표 수집 실패 (로컬 대체 모드): {e}")

    # 정밀 오버나잇 시간 윈도우 결정 (KST 기준)
    window_start = datetime(cur_date.year, cur_date.month, cur_date.day, 15, 30, tzinfo=KST)
    if is_friday:
        # 금요일 15:30 ~ 월요일 10:30 (주말 65시간 + 월요일 오전)
        end_d = cur_date + timedelta(days=3)
    else:
        # 평일(월~목): 오늘 15:30 ~ 익일 10:30 (미국 야간 지표 + 익일 오전 10:00 금통위 포함)
        end_d = cur_date + timedelta(days=1)
    window_end = datetime(end_d.year, end_d.month, end_d.day, 10, 30, tzinfo=KST)

    detected_shocks = []
    seen_desc_keys = set()
    total_risk_score = 0

    for ev in macro_events:
        try:
            ev_date = ev.get("parsed_date")
            if not ev_date and ev.get("date"):
                ev_date = datetime.strptime(str(ev["date"]), "%Y-%m-%d").date()
            if not ev_date:
                continue

            # 발표 완료된 것은 리스크에서 제외
            if ev.get("is_release"):
                continue

            # 발표 시각(parsed_time)이 있으면 정밀 시간 윈도우(15:30 ~ 익일 10:30) 비교
            ev_time = ev.get("parsed_time")
            if ev_time is not None:
                ev_dt = datetime(ev_date.year, ev_date.month, ev_date.day, ev_time.hour, ev_time.minute, tzinfo=KST)
                if not (window_start <= ev_dt <= window_end):
                    continue
            else:
                if not (cur_date <= ev_date <= end_d):
                    continue

            ev_name = str(ev.get("event", ""))
            ev_name_low = ev_name.lower()
            country = str(ev.get("country", ""))
            is_us = any(c in country.lower() for c in ("미국", "us", "usd", "usa"))

            for kw_tuple, weight, desc, us_only in HIGH_IMPACT_MACRO_KEYWORDS:
                if us_only and country and not is_us:
                    continue
                if any(kw in ev_name_low for kw in kw_tuple):
                    # 동일 유형 지표(예: Core PCE MoM + YoY 동시 발표) 중복 가산 방지
                    dedup_key = f"{ev_date}:{desc}"
                    time_str = ev.get("time", "")
                    detected_shocks.append({
                        "event": ev_name,
                        "desc": desc,
                        "date": ev_date.strftime("%Y-%m-%d"),
                        "time": time_str,
                        "country": country,
                        "weight": weight if dedup_key not in seen_desc_keys else 0
                    })
                    if dedup_key not in seen_desc_keys:
                        seen_desc_keys.add(dedup_key)
                        total_risk_score += weight
                    break
        except Exception:
            continue

    # 마스터 캘린더(한국은행 금통위 D-0/D-1) 및 국내 네 마녀의 날(D-0) 연동
    try:
        next_day = cur_date + timedelta(days=1)
        for me in load_global_master_events(cur_date):
            if me.get("category") == "BOK_RATE" and me.get("date") == next_day.strftime("%Y-%m-%d"):
                dedup_key = f"{next_day}:한국은행 금통위 기준금리 결정"
                if dedup_key not in seen_desc_keys:
                    seen_desc_keys.add(dedup_key)
                    detected_shocks.append({
                        "event": me.get("title", "한국은행 금통위"),
                        "desc": "한국은행 금통위 기준금리 결정",
                        "date": me["date"],
                        "time": "10:00",
                        "country": "한국",
                        "weight": 50
                    })
                    total_risk_score += 50
        deriv = get_next_derivatives_expiry(cur_date)
        next_quad = deriv.get("next_quadruple") if isinstance(deriv, dict) else None
        if next_quad and next_quad.get("d_day") in (0, 1) and next_quad.get("date") == next_day.strftime("%Y-%m-%d"):
            dedup_key = f"{next_day}:네마녀의날"
            if dedup_key not in seen_desc_keys:
                seen_desc_keys.add(dedup_key)
                detected_shocks.append({
                    "event": next_quad.get("name", "국내 선물·옵션 동시만기일"),
                    "desc": "국내 네 마녀의 날 (선물·옵션 동시만기)",
                    "date": next_quad["date"],
                    "time": "09:00",
                    "country": "한국",
                    "weight": 50
                })
                total_risk_score += 50
    except Exception as _me:
        logger.debug(f"마스터/파생 일정 연동 예외: {_me}")

    # 금요일 주말 페널티: 주말 65시간 미대응 리스크 가산점 (+20)
    if is_friday:
        total_risk_score += 20

    # 스코어 클램프
    total_risk_score = min(100, max(0, total_risk_score))

    # 등급 산출
    if is_friday:
        # 금요일은 원칙적으로 매수 차단 유지
        level = "RED" if total_risk_score >= 50 else "YELLOW"
        recommendation = "BLOCK_BETTING"
        status_msg = "주말 65시간 미대응 리스크 방어 (100% 현금 보존 권장)"
    else:
        if total_risk_score >= 80:
            level = "RED"
            recommendation = "BLOCK_BETTING"
            status_msg = f"오늘 밤 초고위험 경제지표 발표 ({len(detected_shocks)}건 감지) ➔ 매수 전면 차단 권장"
        elif total_risk_score >= 50:
            level = "YELLOW"
            recommendation = "HALF_BETTING"
            status_msg = f"오늘 밤 주요 지표 발표 예정 ➔ 투자금 50% 축소(하프 켈리) 권장"
        else:
            level = "GREEN"
            recommendation = "NORMAL_BETTING"
            status_msg = "오늘 밤 위험 경제지표 없음 ➔ 정상 오버나잇 베팅 허용"

    return {
        "score": total_risk_score,
        "level": level,
        "recommendation": recommendation,
        "status_message": status_msg,
        "is_friday": is_friday,
        "detected_events": detected_shocks
    }


# ---------------------------------------------------------------------------
# 5. 통합 인텔리전스 빌더 및 캐시 저장
# ---------------------------------------------------------------------------
def build_and_save_event_intelligence(ref_datetime: datetime = None) -> dict:
    """
    모든 이벤트 인텔리전스를 통합하여 data/event_risk_cache.json에 저장하고 딕셔너리 반환
    """
    if ref_datetime is None:
        ref_datetime = get_current_kst()

    ref_date = ref_datetime.date()

    # 1) 파생 만기일
    derivatives = get_next_derivatives_expiry(ref_date)

    # 2) 글로벌 마스터 이벤트 (금통위, MSCI, 전시회)
    master_events = load_global_master_events(ref_date)

    # 3) 자사주 소각 호재
    burn_catalysts = extract_burn_catalysts(ref_date)

    # 4) 야간 거시 리스크
    overnight_risk = evaluate_overnight_event_risk(ref_datetime)

    # 5) 종목별 가산점 매핑 테이블 생성 (stock_boost_map)
    stock_boost_map = {}
    for bc in burn_catalysts:
        stock_boost_map[bc["corp_name"]] = {
            "boost_score": bc["boost_score"],
            "tag": bc["tag"],
            "reason": f"자사주 시총 {bc['ratio_pct']:.2f}% 영구소각 호재"
        }

    intelligence = {
        "updated_at": ref_datetime.strftime("%Y-%m-%d %H:%M:%S"),
        "overnight_risk": overnight_risk,
        "derivatives": derivatives,
        "upcoming_catalysts": master_events[:6],
        "burn_catalysts": burn_catalysts,
        "stock_boost_map": stock_boost_map
    }

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cache_path = os.path.join(base_dir, "data", "event_risk_cache.json")
    try:
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(intelligence, f, ensure_ascii=False, indent=2)
        logger.info(f"이벤트 인텔리전스 캐시 저장 완료: {cache_path}")
    except Exception as e:
        logger.error(f"이벤트 캐시 저장 실패: {e}")

    return intelligence


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    intel = build_and_save_event_intelligence()
    print("=== OVERNIGHT RISK ===")
    print(json.dumps(intel["overnight_risk"], ensure_ascii=False, indent=2))
    print("\n=== DERIVATIVES EXPIRY ===")
    print(json.dumps(intel["derivatives"], ensure_ascii=False, indent=2))
    print("\n=== UPCOMING CATALYSTS ===")
    for c in intel["upcoming_catalysts"]:
        print(f"[{c['category']}] D-{c['d_day']} | {c['date']} : {c['title']}")
    print("\n=== BURN CATALYSTS ===")
    for b in intel["burn_catalysts"]:
        print(f"{b['corp_name']}: {b['tag']} (Boost: +{b['boost_score']})")
