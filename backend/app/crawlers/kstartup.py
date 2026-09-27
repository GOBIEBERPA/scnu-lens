"""공공데이터포털의 '창업진흥원_K-Startup 조회서비스'에서 대학생이 신청할 수 있는 창업 경진대회·교육·행사 공고를 가져온다.

K-Startup에는 기업 대상 공고(입주기업 모집, 융자 등)가 대부분이라, 신청 대상에 '대학생'이 있고
전국·전남광주에서 열리는 공고 중 학생에게 쓸모 있는 분야만 남긴다.
"""

import html
import re
from datetime import date, datetime

import httpx

from app.config import get_settings
from app.crawlers.base import BaseCrawler, CrawledNotice

API_URL = "https://apis.data.go.kr/B552735/kisedKstartupService01/getAnnouncementInformation01"
DETAIL_URL = "https://www.k-startup.go.kr/web/contents/bizpbanc-ongoing.do?schM=view&pbancSn={sn}"
PAGE_SIZE = 100
# 최신 공고부터 온다. 모집 중인 공고는 앞쪽 몇 페이지에 몰려 있다.
MAX_PAGES = 5
REGIONS = frozenset({"전국", "전남", "광주", "전남광주"})
# 입주 공간·융자·보증·수출 지원은 기업 대상이라 뺀다.
STUDENT_FIELDS = frozenset({"사업화", "창업교육", "멘토링ㆍ컨설팅ㆍ교육", "행사ㆍ네트워크", "글로벌"})
BODY_LIMIT = 1500
# '대학생'이 신청 대상에 있어도 실제로는 기업용인 공고(IR·입주·기업 모집)가 많아 제목으로 한 번 더 거른다.
# 경진대회류는 "참가기업 모집"이라도 학생 팀이 나갈 수 있어 남기고, 그 밖에는 청년·학생용 제목만 남긴다.
CONTEST_RE = re.compile(r"경진대회|공모전|해커톤|hackathon|챌린지|아이디어|창업대회|기업가대상", re.IGNORECASE)
YOUTH_RE = re.compile(r"청년|대학|학생|예비\s*창업|아카데미|부트캠프|캠프|교육생|수강")
BUSINESS_RE = re.compile(r"기업\s*모집|참여\s*기업|입주|소상공인|중소기업|투자\s*유치|주관기관|TIPS|\bIR\b|밋업|피칭")


# API가 지역을 '전국'으로 적어도, 제목·주관에 다른 지역 이름이 있으면 그 지역 주민·학생 한정인 경우가 대부분이다
# (예: [도봉구청년창업센터], 마포 청년 창업 경진대회, G밸리창업경진대회). 순천대 학생에게는 보여주지 않는다.
ELSEWHERE_RE = re.compile(
    r"서울|도봉|마포|강남|강북|강서|강동|관악|구로|금천|노원|동작|성동|성북|송파|양천|영등포|용산|은평|종로|중랑|광진|동대문|서대문|서초|"
    r"G\s*밸리|경기|수원|성남|용인|고양|부천|안산|안양|화성|평택|인천|부산|대구|대전(?!환)|울산|세종|강원|춘천|원주|"
    r"충북|충남|충청|청주|천안|전북|전주|경북|경남|경상|포항|창원|제주",
    re.IGNORECASE,
)
HOME_REGION_RE = re.compile(r"전남|전라남도|광주|순천|여수|목포|광양|나주")
# 주관 기관은 지자체일 때만 지역 한정으로 본다. "서울핀테크랩" 주관 해커톤처럼 기관만 서울이고 전국 대상인 공고가 많다.
LOCAL_GOV_RE = re.compile(r"구청|시청|군청|도청|구\s*청년|시\s*청년")


def local_elsewhere(title: str, host: str = "") -> bool:
    """입력: 공고명·주관 기관, 출력: 전남·광주가 아닌 다른 지역 한정 공고로 보이는지 여부.

    제목에 다른 지역 이름이 있거나, 주관이 다른 지역 지자체일 때만 뺀다.
    """
    if HOME_REGION_RE.search(f"{title} {host}"):
        return False
    return bool(ELSEWHERE_RE.search(title) or (LOCAL_GOV_RE.search(host) and ELSEWHERE_RE.search(host)))


def student_title(title: str) -> bool:
    """입력: 공고명, 출력: 학생이 볼 만한 공고(경진대회류, 또는 기업용 표현이 없는 청년·학생 대상)인지 여부."""
    return bool(CONTEST_RE.search(title) or (YOUTH_RE.search(title) and not BUSINESS_RE.search(title)))


def _as_date(value: object) -> str | None:
    """입력: YYYYMMDD 문자열, 출력: YYYY-MM-DD 또는 형식이 틀리면 None."""
    text = str(value or "").strip()
    try:
        return datetime.strptime(text, "%Y%m%d").date().isoformat()
    except ValueError:
        return None


def is_for_students(row: dict, today: str) -> bool:
    """입력: 공고 행·오늘(YYYY-MM-DD), 출력: 대학생이 지금 신청할 수 있는 학생용 분야 공고인지 여부."""
    end = _as_date(row.get("pbanc_rcpt_end_dt"))
    return (
        bool(end and end >= today)
        and "대학생" in str(row.get("aply_trgt") or "")
        and str(row.get("supt_regin") or "") in REGIONS
        and str(row.get("supt_biz_clsfc") or "") in STUDENT_FIELDS
        and student_title(_clean(row.get("biz_pbanc_nm")))
        and not local_elsewhere(_clean(row.get("biz_pbanc_nm")), _clean(row.get("pbanc_ntrp_nm") or row.get("sprv_inst")))
    )


def _clean(value: object) -> str:
    """입력: API 문자열(&apos; 같은 HTML 엔티티·겹친 공백 포함), 출력: 정리된 문자열."""
    return " ".join(html.unescape(str(value or "")).split())


def row_notice(row: dict) -> CrawledNotice | None:
    """입력: 공고 행, 출력: 공지 한 건; 공고명·번호·마감일이 없으면 None."""
    title = _clean(row.get("biz_pbanc_nm"))
    serial = str(row.get("pbanc_sn") or "").strip()
    deadline = _as_date(row.get("pbanc_rcpt_end_dt"))
    if not title or not serial or not deadline:
        return None
    opens = _as_date(row.get("pbanc_rcpt_bgng_dt"))
    host = row.get("pbanc_ntrp_nm") or row.get("sprv_inst")
    contact = " ".join(str(part) for part in (row.get("biz_prch_dprt_nm"), row.get("prch_cnpl_no")) if part)
    body = html.unescape(str(row.get("pbanc_ctnt") or "")).strip()
    lines = [
        # 마감일 추출 규칙이 "까지"를 먼저 보므로 마감 줄을 맨 앞에 둔다.
        f"접수 마감: {deadline}까지",
        f"접수 시작: {opens}" if opens else None,
        f"지원 분야: {row['supt_biz_clsfc']}" if row.get("supt_biz_clsfc") else None,
        f"신청 대상: {row['aply_trgt']}" if row.get("aply_trgt") else None,
        f"대상 상세: {row['aply_trgt_ctnt']}" if row.get("aply_trgt_ctnt") else None,
        f"대상 연령: {row['biz_trgt_age']}" if row.get("biz_trgt_age") else None,
        f"지역: {row['supt_regin']}" if row.get("supt_regin") else None,
        f"주관: {host}" if host else None,
        f"문의: {contact}" if contact else None,
        body[:BODY_LIMIT] if body else None,
        "출처: 창업진흥원 K-Startup(공공데이터포털)",
    ]
    return CrawledNotice(
        external_id=f"kstartup-{serial}",
        title=title,
        url=str(row.get("detl_pg_url") or "") or DETAIL_URL.format(sn=serial),
        raw_text="\n".join(line for line in lines if line),
        published_at=datetime.fromisoformat(opens) if opens else None,
    )


class KStartupCrawler(BaseCrawler):
    """K-Startup 공고 중 대학생이 지금 신청할 수 있는 것을 마감 빠른 순으로 돌려준다."""

    # 학교 게시판 한 곳(기본 10건)보다 공고가 훨씬 많다.
    limit_override = 40

    async def crawl(self) -> list[CrawledNotice]:
        """입력 없음, 출력: 학생 대상 모집 중 공고; 키가 없거나 실패하면 빈 목록."""
        key = get_settings().data_go_kr_key
        if not key:
            return []
        today = date.today().isoformat()
        picked: dict[str, CrawledNotice] = {}
        deadlines: dict[str, str] = {}
        async with httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=10.0)) as client:
            for row in await self._fetch(client, key):
                if not is_for_students(row, today):
                    continue
                if (notice := row_notice(row)) and notice.external_id not in picked:
                    picked[notice.external_id] = notice
                    deadlines[notice.external_id] = _as_date(row.get("pbanc_rcpt_end_dt")) or ""
        ordered = sorted(picked.values(), key=lambda notice: deadlines[notice.external_id])
        return ordered[: self.limit]

    async def _fetch(self, client: httpx.AsyncClient, key: str) -> list[dict]:
        """입력: 클라이언트·인증키, 출력: 앞쪽 몇 페이지의 공고 행."""
        rows: list[dict] = []
        for page in range(1, MAX_PAGES + 1):
            params = {"serviceKey": key, "page": page, "perPage": PAGE_SIZE, "returnType": "json"}
            try:
                response = await client.get(API_URL, params=params)
                response.raise_for_status()
                data = response.json().get("data") or []
            except Exception:
                break
            rows.extend(data)
            if len(data) < PAGE_SIZE:
                break
        return rows
