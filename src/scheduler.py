"""
APScheduler를 사용한 일정 관리
매일 정해진 시간에 경제 캘린더 데이터를 수집하고 텔레그램으로 전송
"""
import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import atexit
import time
from datetime import datetime

from src.digest import build_daily_digest
from src.telegram_sender import send_economic_calendar_to_telegram_sync

logger = logging.getLogger(__name__)


class EconomicCalendarScheduler:
    """경제 캘린더 정기 전송 스케줄러"""
    
    def __init__(self, bot_token, chat_id, hour=7, minute=0):
        """
        초기화
        
        Args:
            bot_token (str): 텔레그램 봇 토큰
            chat_id (str): 텔레그램 채팅 ID
            hour (int): 전송 시간 (기본값 7시)
            minute (int): 전송 분 (기본값 0분)
        """
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.hour = hour
        self.minute = minute
        
        self.scheduler = BackgroundScheduler()
        
        # 프로그램 종료 시 스케줄러도 종료
        atexit.register(lambda: self.stop())
    
    def start(self):
        """스케줄러 시작"""
        if self.scheduler.running:
            logger.warning("스케줄러가 이미 실행 중입니다")
            return
        
        # 월요일부터 금요일까지 지정된 시간에 작업 실행
        self.scheduler.add_job(
            func=self.send_economic_calendar,
            trigger=CronTrigger(day_of_week='mon-fri', hour=self.hour, minute=self.minute),
            id='economic_calendar_daily',
            name='경제 캘린더 일일 전송',
            replace_existing=True
        )
        
        self.scheduler.start()
        logger.info(f"스케줄러 시작: 매일 {self.hour:02d}:{self.minute:02d}에 실행")
    
    def stop(self):
        """스케줄러 중지"""
        if self.scheduler.running:
            self.scheduler.shutdown()
            logger.info("스케줄러 중지됨")
    
    def send_economic_calendar(self):
        """
        시황 + 경제 캘린더 데이터 수집 및 텔레그램 전송
        """
        try:
            logger.info(f"[{datetime.now()}] 시황 + 경제 캘린더 데이터 수집 시작")
            
            # 데이터 수집
            digest = build_daily_digest()
            
            # 1. 날씨 메시지 전송
            success_weather = send_economic_calendar_to_telegram_sync(
                digest['weather_message'],
                self.bot_token,
                self.chat_id
            )
            
            # 메시지 간 간격을 두기 위해 3초 대기
            time.sleep(3)
            
            # 2. 경제 캘린더 메시지 전송
            success_economic = send_economic_calendar_to_telegram_sync(
                digest['economic_message'],
                self.bot_token,
                self.chat_id
            )
            
            if success_weather and success_economic:
                logger.info(f"[{datetime.now()}] 시황 + 경제 캘린더 전송 성공 (이벤트 수: {len(digest['events'])})")
            else:
                logger.error(f"[{datetime.now()}] 시황 + 경제 캘린더 전송 실패")
        
        except Exception as e:
            logger.error(f"[{datetime.now()}] 시황 + 경제 캘린더 처리 중 오류: {e}", exc_info=True)
    
    def get_jobs(self):
        """
        현재 등록된 작업 목록 반환
        
        Returns:
            list: 작업 객체 리스트
        """
        return self.scheduler.get_jobs()
    
    def trigger_now(self):
        """
        즉시 날씨 + 경제 캘린더 전송 (테스트용)
        """
        logger.info("날씨 + 경제 캘린더 즉시 전송 (테스트)")
        self.send_economic_calendar()


def create_scheduler(bot_token, chat_id, hour=7, minute=0):
    """
    스케줄러 생성 및 시작
    
    Args:
        bot_token (str): 텔레그램 봇 토큰
        chat_id (str): 텔레그램 채팅 ID
        hour (int): 전송 시간
        minute (int): 전송 분
    
    Returns:
        EconomicCalendarScheduler: 스케줄러 인스턴스
    """
    scheduler = EconomicCalendarScheduler(bot_token, chat_id, hour, minute)
    scheduler.start()
    return scheduler
