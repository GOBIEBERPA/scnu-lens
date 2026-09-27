"""로컬 LLM(Ollama)로 공지 구조화를 보강하고, 원문에서 확인되지 않는 값은 버린다.

LLM은 규칙 기반 결과를 대체하지 않고 '제안'만 한다. 제안이 원문으로 검증되지 않으면
규칙 결과를 그대로 쓰기 때문에, 모델이 마감일을 지어내도 학생에게 노출되지 않는다.
"""

import json
import re
from datetime import date

import httpx

from app.config import Settings
from app.schemas import NoticeStructured

PROMPT = """너는 대학 공지를 읽고 정보를 뽑는 추출기다. 새로운 사실을 지어내지 마라.

규칙:
- deadline: 신청/접수/제출 마감일이 본문에 명시된 경우에만 YYYY-MM-DD로 적는다. 없으면 null.
  본문에 없는 날짜를 절대 만들지 마라. 기간이면 마지막(종료) 날짜를 쓴다.
- target_departments: 이 공지가 대상으로 삼는 학과/학부/전공 이름만. 서식 작성 예시나
  담당 부서 이름은 대상이 아니다. 없으면 빈 배열.
- target_students: 재학생, 신입생, 3학년처럼 대상 학생 구분. 없으면 빈 배열.
- category: 다음 중 하나만 고른다. {categories}
- summary: 학생이 무엇을 해야 하는지 한국어 2문장 이내.
- topics: 공지의 주제에 해당하는 것만 다음 목록에서 고른다. 목록에 없는 말은 쓰지 마라. 없으면 빈 배열.
  목록: {topics}

JSON만 출력하라.
{{"category": "...", "summary": "...", "deadline": null, "target_departments": [], "target_students": [], "topics": []}}

제목: {title}
게시일: {published}
본문:
{body}
"""


FILL_PROMPT = """아래 공지 본문에서 요청한 항목의 값을 찾아라.
- 값은 반드시 본문에 적힌 문구를 그대로 옮겨라. 바꿔 쓰거나 요약하지 마라.
- 본문에 없으면 null로 둬라. 추측하지 마라.
- 항목: {fields}

JSON만 출력하라. 예: {{"대상": "재학생", "문의": null}}

제목: {title}
본문:
{body}
"""


def _squash(text: str) -> str:
    """입력: 문자열, 출력: 공백을 모두 뺀 문자열; 원문 포함 여부 비교용."""
    return re.sub(r"\s+", "", text)


class LlmStructurer:
    """Ollama의 로컬 모델에 구조화를 요청하고 결과를 원문으로 검증한다."""

    def __init__(self, settings: Settings) -> None:
        """입력: 앱 설정, 출력 없음; 호출 대상 엔드포인트와 모델을 보관한다."""
        self.settings = settings
        self.endpoint = f"{settings.llm_base_url.rstrip('/')}/api/generate"

    async def refine(self, base: NoticeStructured, title: str, body: str, published: date | None) -> NoticeStructured:
        """입력: 규칙 기반 결과·원문, 출력: 검증을 통과한 항목만 반영한 구조화 결과."""
        payload = await self._ask(title, body, published)
        if not payload:
            return base
        return base.model_copy(
            update={
                "category": self._pick_category(payload.get("category"), base.category),
                "summary": self._pick_summary(payload.get("summary"), base.summary),
                "deadline": self._pick_deadline(payload.get("deadline"), body, base.deadline),
                "target_departments": self._verified_terms(payload.get("target_departments"), body)
                or base.target_departments,
                "target_students": self._verified_terms(payload.get("target_students"), body)
                or base.target_students,
                "topics": self._allowed_topics(payload.get("topics")),
            }
        )

    @staticmethod
    def _allowed_topics(candidates: object) -> list[str]:
        """입력: 모델이 고른 주제 목록, 출력: 정해진 주제 목록에 있는 값만(소문자) 남긴 목록.

        주제는 본문에 그 단어가 없어도 되는 대신, 미리 정한 목록 밖의 말은 전부 버린다.
        """
        from app.services.ai import INTEREST_SYNONYMS

        if not isinstance(candidates, list):
            return []
        picked = [c.strip().lower() for c in candidates if isinstance(c, str)]
        return list(dict.fromkeys(topic for topic in picked if topic in INTEREST_SYNONYMS))[:6]

    async def fill_brief(self, fields: list[str], title: str, body: str) -> dict[str, str]:
        """입력: 못 찾은 칸 이름·제목·본문, 출력: 본문에 그대로 있는 값으로만 채운 {칸: 값}."""
        payload = await self._generate(FILL_PROMPT.format(fields=", ".join(fields), title=title, body=body[:6000]))
        if not payload:
            return {}
        haystack = _squash(f"{title}{body}")
        verified: dict[str, str] = {}
        for field in fields:
            value = payload.get(field)
            # 모델이 원문을 바꿔 쓰거나 지어냈다면 본문에 없으므로 버린다.
            if isinstance(value, str) and len(_squash(value)) >= 2 and _squash(value) in haystack:
                verified[field] = value.strip()
        return verified

    async def _ask(self, title: str, body: str, published: date | None) -> dict | None:
        """입력: 제목·본문·게시일, 출력: 모델이 반환한 JSON 또는 실패 시 None."""
        from app.services.ai import INTEREST_SYNONYMS, VALID_CATEGORIES

        prompt = PROMPT.format(
            categories=", ".join(VALID_CATEGORIES),
            topics=", ".join(INTEREST_SYNONYMS),
            title=title,
            published=published or "미상",
            body=body[:6000],
        )
        return await self._generate(prompt)

    async def _generate(self, prompt: str) -> dict | None:
        """입력: 프롬프트, 출력: 모델이 반환한 JSON 객체 또는 실패 시 None."""
        request = {
            "model": self.settings.llm_model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {"temperature": 0},
        }
        if self.settings.llm_num_threads:
            request["options"]["num_thread"] = self.settings.llm_num_threads
        try:
            async with httpx.AsyncClient(timeout=self.settings.llm_timeout_seconds) as client:
                response = await client.post(self.endpoint, json=request)
                response.raise_for_status()
                data = json.loads(response.json()["response"])
                return data if isinstance(data, dict) else None
        except Exception:
            return None

    @staticmethod
    def _pick_category(candidate: object, fallback: str) -> str:
        """입력: 모델이 고른 카테고리·규칙 결과, 출력: 허용된 값이면 모델 값, 아니면 규칙 값."""
        from app.services.ai import VALID_CATEGORIES

        return candidate if isinstance(candidate, str) and candidate in VALID_CATEGORIES else fallback

    @staticmethod
    def _pick_summary(candidate: object, fallback: str) -> str:
        """입력: 모델 요약·규칙 발췌, 출력: 길이가 타당한 모델 요약 또는 규칙 발췌."""
        if isinstance(candidate, str) and 10 <= len(candidate.strip()) <= 400:
            return " ".join(candidate.split())
        return fallback

    @staticmethod
    def _pick_deadline(candidate: object, body: str, fallback: str | None) -> str | None:
        """입력: 모델 마감일·본문·규칙 결과, 출력: 본문에서 확인되는 경우에만 모델 값."""
        if not isinstance(candidate, str) or not deadline_supported_by_text(candidate, body):
            return fallback
        return candidate

    @staticmethod
    def _verified_terms(candidates: object, body: str) -> list[str]:
        """입력: 모델이 뽑은 용어 목록·본문, 출력: 본문에 실제로 등장하는 용어만 남긴 목록."""
        if not isinstance(candidates, list):
            return []
        verified = [
            term.strip()
            for term in candidates
            if isinstance(term, str) and term.strip() and term.strip() in body
        ]
        return list(dict.fromkeys(verified))[:8]


def deadline_supported_by_text(iso_date: str, body: str) -> bool:
    """입력: ISO 마감일 후보·본문, 출력: 그 날짜가 본문에 어떤 표기로든 등장하는지 여부."""
    try:
        parsed = date.fromisoformat(iso_date)
    except ValueError:
        return False
    compact = re.sub(r"\s", "", body)
    month, day, year = parsed.month, parsed.day, parsed.year
    forms = {
        f"{year}-{month:02d}-{day:02d}",
        f"{year}.{month:02d}.{day:02d}",
        f"{year}.{month}.{day}",
        f"{year}/{month}/{day}",
        f"{year}년{month}월{day}일",
        f"{month}월{day}일",
        f"{month:02d}월{day:02d}일",
        f"{month}.{day}",
        f"{month:02d}.{day:02d}",
        f"{month}/{day}",
    }
    return any(form in compact for form in forms)
