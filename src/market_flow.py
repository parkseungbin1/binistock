# -*- coding: utf-8 -*-
"""
Today's Market Flow (오늘의 시장 흐름 / 머니플로우 전광판)
Scrapes & models market-wide sector money flow, leaders, and trading volumes.
Inspired by AwakePlus today_market_flow with zero paywall & BiniStock integration.
"""

import os
import re
import json
import logging
import urllib.request
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))

logger = logging.getLogger("market_flow")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
CACHE_FILE = os.path.join(DATA_DIR, "market_flow_cache.json")

def clean_stock_name(raw_name: str):
    """Separate stock name and star badges."""
    stars = "".join(re.findall(r'[⭐️★]+', raw_name))
    name = re.sub(r'[⭐️★\s]+', '', raw_name).strip()
    return name, stars

def parse_volume_to_eok(vol_str: str) -> float:
    """Convert volume string (e.g., '1,236억', '1.9조') to float eok (억원)."""
    if not vol_str:
        return 0.0
    vol_str = vol_str.replace(',', '').strip()
    try:
        if '조' in vol_str:
            val = float(vol_str.replace('조', ''))
            return val * 10000.0
        elif '억' in vol_str:
            val = float(vol_str.replace('억', ''))
            return val
        elif '만' in vol_str:
            val = float(vol_str.replace('만', ''))
            return val / 10000.0
    except Exception:
        pass
    return 0.0

def fetch_awake_market_flow():
    """
    Scrape real-time market flow from AwakePlus.
    Returns list of sector dictionaries.
    """
    url = "https://www.awakeplus.co.kr/home/today_market_flow"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    }
    
    req = urllib.request.Request(url, headers=headers)
    sectors = []
    
    try:
        from bs4 import BeautifulSoup
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode('utf-8', errors='ignore')
            
        soup = BeautifulSoup(html, 'html.parser')
        
        headers_el = soup.find_all(class_='tmf-card-header')
        cards = [h.parent for h in headers_el] if headers_el else soup.find_all(class_='tmf-card')
        
        for card in cards:
            header_el = card.find(class_='tmf-card-header')
            raw_title = header_el.get_text(strip=True) if header_el else ""
            if not raw_title.startswith('#'):
                continue
                
            badge_el = card.find(class_='tmf-sector-badge')
            badge_classes = badge_el.get('class', []) if badge_el else []
            if 'tmf-up' in badge_classes:
                direction = "UP"
            elif 'tmf-down' in badge_classes:
                direction = "DOWN"
            else:
                direction = "NEUTRAL"
                
            # Extract sector name and stars
            sector_stars = "".join(re.findall(r'[⭐️★]+', raw_title))
            sector_name = re.sub(r'[⭐️★]+', '', raw_title).strip()
            
            stocks = []
            sector_total_eok = 0.0
            
            for tr in card.find_all('tr'):
                tds = tr.find_all('td')
                if not tds or len(tds) < 3:
                    continue
                    
                name_cell = tds[0]
                a_tag = name_cell.find('a')
                code = ""
                if a_tag and 'href' in a_tag.attrs:
                    code_match = re.search(r'code=([0-9A-Za-z]+)', a_tag['href'])
                    if code_match:
                        code = code_match.group(1)
                        
                raw_stock_name = name_cell.get_text(strip=True)
                stock_name, stock_stars = clean_stock_name(raw_stock_name)
                
                change_str = tds[1].get_text(strip=True)
                volume_str = tds[2].get_text(strip=True)
                note_str = tds[3].get_text(strip=True) if len(tds) > 3 else ""
                
                change_val = 0.0
                try:
                    change_val = float(change_str.replace('%', '').replace('+', '').strip())
                except Exception:
                    pass
                    
                eok_val = parse_volume_to_eok(volume_str)
                sector_total_eok += eok_val
                
                stocks.append({
                    "code": code,
                    "name": stock_name,
                    "stars": stock_stars,
                    "change_pct": change_val,
                    "change_str": change_str,
                    "volume_str": volume_str,
                    "volume_eok": round(eok_val, 1),
                    "note": note_str,
                    "leader": bool(stock_stars or (len(stocks) == 0 and eok_val > 500))
                })
                
            stocks.sort(key=lambda x: (len(x['stars']), x['volume_eok'], x['change_pct']), reverse=True)
            
            if sector_total_eok >= 10000:
                tot_str = f"{round(sector_total_eok / 10000, 1)}조"
            else:
                tot_str = f"{int(round(sector_total_eok)):,}억"
                
            sectors.append({
                "sector_name": sector_name,
                "stars": sector_stars,
                "direction": direction,
                "total_volume_str": tot_str,
                "total_volume_eok": round(sector_total_eok, 1),
                "stock_count": len(stocks),
                "stocks": stocks
            })
            
        logger.info(f"Successfully scraped {len(sectors)} sectors from AwakePlus")
    except Exception as e:
        logger.warning(f"AwakePlus scrape failed ({e}), checking cache...")
        
    return sectors

def get_market_flow_data(force_refresh: bool = False):
    """
    Get market flow data with cache persistence.
    """
    os.makedirs(DATA_DIR, exist_ok=True)
    
    sectors = []
    try:
        sectors = fetch_awake_market_flow()
    except Exception as e:
        logger.warning(f"Live fetch error: {e}")
        
    if sectors:
        cache_data = {
            "updated_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S"),
            "sector_count": len(sectors),
            "sectors": sectors
        }
        try:
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(cache_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Failed to save market flow cache: {e}")
        return cache_data
        
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to read market flow cache: {e}")
            
    return {
        "updated_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S"),
        "sector_count": 0,
        "sectors": []
    }

def generate_telegram_market_flow_summary():
    """
    Generate brief Telegram-friendly summary of current market flow.
    """
    data = get_market_flow_data()
    sectors = data.get("sectors", [])
    if not sectors:
        return ""
        
    up_sectors = [s for s in sectors if s["direction"] == "UP"]
    down_sectors = [s for s in sectors if s["direction"] == "DOWN"]
    
    lines = ["🔥 <b>[실시간 시장 머니플로우 전광판]</b>"]
    lines.append(f"⏰ 집계시각: {data.get('updated_at', '')}")
    
    if up_sectors:
        lines.append("\n🟢 <b>주요 수급 유입 / 급등 섹터</b>")
        for s in up_sectors[:3]:
            lead_stocks = []
            for st in s["stocks"][:3]:
                st_icon = f"👑{st['name']}" if st['stars'] else st['name']
                lead_stocks.append(f"{st_icon}({st['change_str']}, {st['volume_str']})")
            stocks_text = ", ".join(lead_stocks)
            lines.append(f"• <b>{s['sector_name']}</b> {s['stars']} (합산 {s['total_volume_str']})\n  └ {stocks_text}")
    
    if down_sectors:
        lines.append("\n🔴 <b>거래대금 집중 하락/차익 섹터</b>")
        for s in down_sectors[:3]:
            lead_stocks = []
            for st in s["stocks"][:2]:
                lead_stocks.append(f"{st['name']}({st['change_str']})")
            stocks_text = ", ".join(lead_stocks)
            lines.append(f"• <b>{s['sector_name']}</b> {s['stars']} ({s['total_volume_str']}) └ {stocks_text}")
            
    lines.append("\n👉 <a href='https://parkseungbin1.github.io/binistock/#tab-flow'>전체 섹터 및 전 종목 전광판 보기</a>")
    return "\n".join(lines)

def render_market_flow_html(flow_data: dict) -> str:
    """
    Render AwakePlus-style Market Flow HTML tab contents.
    """
    sectors = flow_data.get('sectors', [])
    updated_at = flow_data.get('updated_at', '')
    if not sectors:
        return """
        <div class="empty-card" style="padding: 40px; text-align: center;">
            <div style="font-size: 2rem; margin-bottom: 12px;">⏳</div>
            <div style="font-size: 1.1rem; font-weight: 700; color: #f3f4f6; margin-bottom: 6px;">
                실시간 머니플로우 전광판 집계 대기 중
            </div>
            <div style="font-size: 0.85rem; color: #9ca3af;">
                장중 거래대금 및 섹터 수급 데이터를 실시간으로 동기화하고 있습니다. 잠시 후 새로고침해주세요.
            </div>
        </div>
        """
        
    up_sectors = [s for s in sectors if s['direction'] == 'UP']
    down_sectors = [s for s in sectors if s['direction'] == 'DOWN']
    
    up_cnt = len(up_sectors)
    down_cnt = len(down_sectors)
    tot_cnt = len(sectors)
    
    html = []
    html.append(f"""
    <div class="tmf-container">
        <!-- 상단 헤더 & 필터 바 -->
        <div class="tmf-hero-box">
            <div class="tmf-hero-left">
                <div class="tmf-hero-title">
                    💸 오늘 돈이 몰리는 곳을 한눈에 <span class="tmf-live-badge">실시간 머니플로우 전광판</span>
                </div>
                <div class="tmf-hero-desc">
                    시장 거래대금이 집중된 주도 섹터와 대장주를 한눈에 스캔합니다. (어웨이크플러스 실시간 데이터 + 네이버 증권 틱차트 연동)
                </div>
            </div>
            <div class="tmf-hero-right">
                <div class="tmf-stat-badge">⏰ 집계시각: <b>{updated_at}</b></div>
                <div class="tmf-stat-badge">📊 총 <b>{tot_cnt}</b>개 섹터 (🟢 강세 {up_cnt} / 🔴 약세 {down_cnt})</div>
            </div>
        </div>

        <!-- 섹터 필터 바 -->
        <div class="tmf-filter-bar">
            <button class="tmf-filter-btn active" onclick="filterFlowSectors('all', this)">
                🌐 전체 섹터 ({tot_cnt})
            </button>
            <button class="tmf-filter-btn tmf-btn-up" onclick="filterFlowSectors('UP', this)">
                🟢 급등/수급유입 ({up_cnt})
            </button>
            <button class="tmf-filter-btn tmf-btn-down" onclick="filterFlowSectors('DOWN', this)">
                🔴 조정/차익실현 ({down_cnt})
            </button>
            <button class="tmf-filter-btn tmf-btn-star" onclick="filterFlowSectors('STAR', this)">
                ⭐️⭐️ 대금 5,000억 이상
            </button>
        </div>

        <!-- 섹터 카드 그리드 -->
        <div class="tmf-grid">
    """)
    
    for sec in sectors:
        sec_name = sec['sector_name']
        sec_stars = sec['stars']
        dir_val = sec['direction']
        tot_vol = sec['total_volume_str']
        stocks = sec['stocks']
        stock_cnt = len(stocks)
        
        dir_badge = "🟢 자금 유입" if dir_val == "UP" else ("🔴 자금 이탈/조정" if dir_val == "DOWN" else "⚪ 보합/혼조")
        dir_class = "tmf-up" if dir_val == "UP" else "tmf-down"
        star_rank = "⭐️⭐️⭐️ (1조+)" if "⭐️⭐️⭐️" in sec_stars else ("⭐️⭐️ (5,000억+)" if "⭐️⭐️" in sec_stars else ("⭐️ (2,000억+)" if "⭐️" in sec_stars else ""))
        
        rows_html = []
        for stock in stocks:
            code = stock['code']
            name = stock['name']
            stars = stock['stars']
            change_str = stock['change_str']
            vol_str = stock['volume_str']
            chg_val = stock['change_pct']
            note = stock['note']
            
            if chg_val > 0:
                chg_cls = "tmf-txt-up"
            elif chg_val < 0:
                chg_cls = "tmf-txt-down"
            else:
                chg_cls = "tmf-txt-even"
                
            badge_html = f'<span class="tmf-stock-stars">{stars}</span>' if stars else ""
            if "⭐️⭐️⭐️" in stars:
                leader_tag = '<span class="tmf-crown-badge">👑 3스타 대장</span>'
            elif "⭐️⭐️" in stars:
                leader_tag = '<span class="tmf-crown-badge-2">⭐ 주도주</span>'
            elif "⭐️" in stars:
                leader_tag = '<span class="tmf-crown-badge-3">관심</span>'
            else:
                leader_tag = ""
                
            naver_url = f"https://finance.naver.com/item/main.naver?code={code}" if code else f"https://finance.naver.com/search/searchList.naver?query={name}"
            note_badge = f'<span class="tmf-note-pill">{note}</span>' if note else ""
            
            rows_html.append(f"""
            <tr>
                <td class="tmf-td-name">
                    <a href="{naver_url}" target="_blank" rel="noopener noreferrer" class="tmf-stock-link">
                        <b>{name}</b>{badge_html}
                    </a>
                    {leader_tag}
                </td>
                <td class="tmf-td-change {chg_cls}"><b>{change_str}</b></td>
                <td class="tmf-td-vol">{vol_str}</td>
                <td class="tmf-td-note">{note_badge}</td>
            </tr>
            """)
            
        rows_str = "".join(rows_html)
        has_many = stock_cnt > 10
        table_container_style = "max-height: 420px; overflow-y: auto;" if has_many else ""
        
        html.append(f"""
        <div class="tmf-card {dir_class}" data-direction="{dir_val}" data-stars="{sec_stars}">
            <div class="tmf-card-header">
                <div class="tmf-header-title-row">
                    <div class="tmf-sector-name">
                        {sec_name} <span class="tmf-sector-stars">{sec_stars}</span>
                    </div>
                    <span class="tmf-dir-badge {dir_class}">{dir_badge}</span>
                </div>
                <div class="tmf-header-sub-row">
                    <span class="tmf-vol-pill">💰 합산 대금: <b>{tot_vol}</b></span>
                    <span class="tmf-cnt-pill">📋 총 <b>{stock_cnt}</b>종목</span>
                    {f'<span class="tmf-star-rank">{star_rank}</span>' if star_rank else ''}
                </div>
            </div>
            <div class="tmf-table-scroll" style="{table_container_style}">
                <table class="tmf-table">
                    <thead>
                        <tr>
                            <th style="width: 44%;">종목명</th>
                            <th style="width: 24%; text-align: right;">수익률</th>
                            <th style="width: 22%; text-align: right;">거래대금</th>
                            <th style="width: 10%; text-align: center;">비고</th>
                        </tr>
                    </thead>
                    <tbody>
                        {rows_str}
                    </tbody>
                </table>
            </div>
        </div>
        """)
        
    html.append("""
        </div>
    </div>
    """)
    return "".join(html)

if __name__ == "__main__":
    data = get_market_flow_data()
    print(f"Loaded {data['sector_count']} sectors")
    html = render_market_flow_html(data)
    print("Rendered length:", len(html))
