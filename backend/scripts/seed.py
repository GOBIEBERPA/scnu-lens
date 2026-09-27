import hashlib
import sys
from datetime import datetime, timedelta
from pathlib import Path

# 직접 실행해도 backend/app 패키지를 찾도록 프로젝트 루트를 import 경로에 추가한다.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.database import SessionLocal, create_tables
from app.models import Notice, UserProfile


SEED_NOTICES = [
    {
        "external_id": "seed-academic-001",
        "source": "데모 학사공지",
        "source_url": "https://www.scnu.ac.kr/",
        "title": "2026학년도 2학기 수강정정 기간 안내",
        "raw_text": "수강정정 기간은 9월 2일부터 9월 6일까지입니다. 향림통에서 신청하고 최종 수강내역을 확인하세요.",
        "category": "학사",
        "structured_json": {
            "title": "2026학년도 2학기 수강정정 기간 안내",
            "category": "학사",
            "summary": "9월 2일부터 6일까지 향림통에서 수강정정을 진행합니다.",
            "deadline": "2026-09-06",
            "target_departments": [],
            "target_students": ["재학생"],
            "keywords": ["수강신청", "수강정정"],
            "action_required": "향림통에서 수강내역 확인",
            "contact": None,
        },
    },
    {
        "external_id": "seed-scholarship-001",
        "source": "데모 장학공지",
        "source_url": "https://www.scnu.ac.kr/",
        "title": "NOVA 마일리지 장학금 신청 안내",
        "raw_text": "재학생 대상 NOVA 마일리지 장학금 신청을 9월 30일까지 받습니다. 활동 증빙을 학생성공플랫폼에 제출하세요.",
        "category": "장학",
        "structured_json": {
            "title": "NOVA 마일리지 장학금 신청 안내",
            "category": "장학",
            "summary": "재학생은 9월 30일까지 활동 증빙과 함께 NOVA 마일리지 장학금을 신청할 수 있습니다.",
            "deadline": "2026-09-30",
            "target_departments": [],
            "target_students": ["재학생"],
            "keywords": ["장학금", "NOVA", "마일리지"],
            "action_required": "학생성공플랫폼에 증빙 제출",
            "contact": None,
        },
    },
    {
        "external_id": "seed-department-001",
        "source": "데모 컴퓨터교육과 공지",
        "source_url": "https://www.scnu.ac.kr/comedu/main.do",
        "title": "AI·SW 융합 아이디어 캠프 참가자 모집",
        "raw_text": "컴퓨터교육과 및 SW 주관학과 학생을 대상으로 AI 아이디어 캠프 참가자를 9월 22일까지 모집합니다.",
        "category": "행사",
        "structured_json": {
            "title": "AI·SW 융합 아이디어 캠프 참가자 모집",
            "category": "행사",
            "summary": "SW 주관학과 학생 대상 AI 아이디어 캠프 참가자를 모집합니다.",
            "deadline": "2026-09-22",
            "target_departments": ["컴퓨터교육과", "컴퓨터공학과", "인공지능공학전공"],
            "target_students": ["재학생"],
            "keywords": ["AI", "SW", "캠프"],
            "action_required": "9월 22일까지 참가 신청",
            "contact": None,
        },
    },
]


def seed() -> None:
    """입력 없음, 출력 없음; 데모 공지 3건과 웹 사용자 1명을 멱등적으로 삽입한다."""
    create_tables()
    with SessionLocal() as db:
        for index, item in enumerate(SEED_NOTICES):
            existing = db.scalar(select(Notice).where(Notice.external_id == item["external_id"], Notice.source == item["source"]))
            if existing:
                continue
            raw_text = str(item["raw_text"])
            db.add(
                Notice(
                    **item,
                    published_at=datetime.now() - timedelta(days=index),
                    content_hash=hashlib.sha256(raw_text.encode("utf-8")).hexdigest(),
                    processing_status="structured",
                )
            )
        demo_user = db.scalar(select(UserProfile).where(UserProfile.web_device_id == "demo-browser"))
        if demo_user is None:
            db.add(
                UserProfile(
                    web_device_id="demo-browser",
                    display_name="데모 학생",
                    department="컴퓨터교육과",
                    interests=["AI", "장학금", "수강신청"],
                )
            )
        db.commit()


if __name__ == "__main__":
    seed()
    print("시드 데이터가 준비되었습니다.")
