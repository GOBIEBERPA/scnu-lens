"""순천대 학과·부속기관 사이트를 훑어 각 사이트의 '공지사항' 게시판 주소를 찾는다.

학교 사이트는 모두 같은 게시판 엔진(/na/ntt/selectNttList.do)을 쓰므로, 주소만 알면
기존 ScnuBoardCrawler로 그대로 수집할 수 있다. 사이트 개편 시 이 스크립트를 다시 돌리면 된다.

    python scripts/discover_boards.py  →  app/crawlers/scnu_boards.json 갱신
"""

import asyncio
import json
import re
import sys
from pathlib import Path
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.crawlers.base import ensure_school_url  # noqa: E402 - 스크립트를 직접 실행할 때 app을 찾도록 경로를 먼저 더한다

BASE = "https://www.scnu.ac.kr"
MAIN = f"{BASE}/SCNU/main.do"
OUTPUT = Path(__file__).resolve().parents[1] / "app" / "crawlers" / "scnu_boards.json"
HEADERS = {"User-Agent": "SCNU-Lens/1.0 (+student-notice-aggregator)"}

# 학교 서버에 부담을 주지 않도록 동시에 몇 개만 요청한다.
CONCURRENCY = 4
# 공지 게시판이 아닌 사이트 경로(이미지·규정집 등)는 건너뛴다.
SKIP_SLUGS = {"SCNU", "images", "rule", "guest", "search", "upload"}
SITE_RE = re.compile(r"^https?://www\.scnu\.ac\.kr/([A-Za-z0-9_]+)/")


async def fetch(client: httpx.AsyncClient, gate: asyncio.Semaphore, url: str) -> str:
    """입력: 클라이언트·동시성 제한·주소, 출력: HTML 문자열; 실패하면 빈 문자열."""
    async with gate:
        try:
            ensure_school_url(url)
            response = await client.get(url, follow_redirects=True)
            ensure_school_url(str(response.url))
            response.raise_for_status()
            await asyncio.sleep(0.2)
            return response.text
        except Exception:
            return ""


def site_links(html: str, page_url: str) -> dict[str, str]:
    """입력: HTML·기준 주소, 출력: {사이트 경로: 링크 텍스트} — www.scnu.ac.kr/<경로>/ 형태만."""
    found: dict[str, str] = {}
    for anchor in BeautifulSoup(html, "html.parser").select("a[href]"):
        match = SITE_RE.match(urljoin(page_url, anchor["href"]))
        if match and match.group(1) not in SKIP_SLUGS:
            text = " ".join(anchor.get_text(" ", strip=True).split())
            found.setdefault(match.group(1), text)
            if text and not found[match.group(1)]:
                found[match.group(1)] = text
    return found


def college_links(html: str) -> set[str]:
    """입력: HTML, 출력: 단과대학·스쿨·학부 소개 페이지 주소 집합(대학원 제외)."""
    return {
        urljoin(MAIN, a["href"])
        for a in BeautifulSoup(html, "html.parser").select('a[href*="cntntsView.do"]')
        if re.search(r"(대학|학부|스쿨|본부직속|융합전공)", a.get_text())
        and "대학원" not in a.get_text()
    }


def clean_name(text: str, slug: str) -> str:
    """입력: 링크 텍스트·경로, 출력: '홈페이지 바로가기' 같은 군더더기와 반복을 뺀 사이트 이름."""
    name = re.sub(r"\s*홈페이지\s*바로가기\s*", " ", text).strip()
    words = name.split()
    half = len(words) // 2
    # "국제농축산학과 국제농축산학과"처럼 같은 말이 두 번 붙은 경우 한 번만 남긴다.
    if half and words[:half] == words[half:]:
        name = " ".join(words[:half])
    return name or slug


def notice_board(html: str, page_url: str) -> str | None:
    """입력: 사이트 메인 HTML, 출력: '공지사항' 게시판 목록 주소 또는 None."""
    candidates: list[tuple[int, str]] = []
    for anchor in BeautifulSoup(html, "html.parser").select('a[href*="selectNttList.do"]'):
        text = " ".join(anchor.get_text(" ", strip=True).split())
        if "공지" not in text:
            continue
        # 정확히 '공지사항'인 메뉴를 가장 우선한다(학사공지·장학공지보다 사이트 대표 공지).
        rank = 0 if text == "공지사항" else 1 if "공지사항" in text else 2
        candidates.append((rank, urljoin(page_url, anchor["href"])))
    return min(candidates)[1] if candidates else None


async def main() -> None:
    """입력 없음, 출력 없음; 사이트를 찾고 공지 게시판 주소를 JSON으로 저장한다."""
    gate = asyncio.Semaphore(CONCURRENCY)
    async with httpx.AsyncClient(headers=HEADERS, timeout=httpx.Timeout(20.0, connect=10.0)) as client:
        main_html = await fetch(client, gate, MAIN)
        if not main_html:
            sys.exit("메인 페이지를 가져오지 못했습니다.")
        sites = site_links(main_html, MAIN)

        # 단과대학·스쿨 소개 페이지에 학과 홈페이지 링크가 모여 있다.
        # 학제 개편으로 단과대학 일부가 "○○스쿨"이 됐고, 메인에는 그중 일부만 걸려 있어
        # 소개 페이지에서 다시 찾은 소개 페이지까지 한 번 더 따라간다.
        college_pages = college_links(main_html)
        visited: set[str] = set()
        for _ in range(2):
            pending = sorted(college_pages - visited)
            visited |= set(pending)
            for html in await asyncio.gather(*(fetch(client, gate, url) for url in pending)):
                college_pages |= college_links(html)
                for slug, text in site_links(html, MAIN).items():
                    sites.setdefault(slug, text)

        slugs = sorted(sites)
        homes = await asyncio.gather(*(fetch(client, gate, f"{BASE}/{slug}/main.do") for slug in slugs))

    boards = []
    for slug, html in zip(slugs, homes):
        board = notice_board(html, f"{BASE}/{slug}/main.do") if html else None
        if not board:
            continue
        title = BeautifulSoup(html, "html.parser").title
        page_title = title.get_text(strip=True) if title else ""
        # 링크 글자가 "홈페이지 바로가기"뿐이면 이름이 비므로, 사이트 <title>로 대신한다.
        site_name = clean_name(sites[slug], "") or clean_name(page_title, slug)
        boards.append({"slug": slug, "name": site_name, "url": board})

    OUTPUT.write_text(json.dumps(boards, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"사이트 {len(slugs)}곳 확인, 공지사항 게시판 {len(boards)}곳 저장 → {OUTPUT}")


if __name__ == "__main__":
    asyncio.run(main())
