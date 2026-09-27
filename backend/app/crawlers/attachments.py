"""공지 첨부파일(HWP·HWPX·PDF·DOCX)에서 본문 텍스트를 뽑는다.

학교 공지는 본문에 "붙임 참조"만 쓰고 신청기간·대상은 첨부 한글 파일에만 적는 경우가 많다.
첨부 텍스트를 본문 뒤에 붙여 두면 마감일·상세 칸 추출이 같은 규칙으로 그대로 동작한다.
"""

import io
import re
import struct
import zipfile
import zlib
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from app.crawlers.base import ensure_school_url

# 공지 하나에서 읽을 첨부 수·파일 크기·글자 수 상한. 포스터·대용량 자료로 수집이 느려지지 않게 한다.
MAX_ATTACHMENTS = 3
MAX_BYTES = 5 * 1024 * 1024
MAX_CHARS_PER_FILE = 6000
PDF_MAX_PAGES = 10
READABLE_EXTENSIONS = (".hwpx", ".hwp", ".pdf", ".docx")
DOWNLOAD_PATH = "nttFileDownload.do"

# HWP 본문 레코드 태그(HWPTAG_BEGIN 16 + 51)와, 뒤에 7글자를 더 차지하는 인라인·확장 컨트롤 문자.
HWPTAG_PARA_TEXT = 67
HWP_WIDE_CONTROLS = frozenset({1, 2, 3, 4, 5, 6, 7, 8, 9, 11, 12, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23})

# 붙인 첨부 구간의 머리말. 화면·검증 코드가 본문과 첨부를 구분할 때 쓴다.
ATTACHMENT_HEADER = "[첨부파일: {name}]"


def body_only(raw_text: str) -> str:
    """입력: 첨부가 붙었을 수 있는 원문, 출력: 첫 첨부 머리말 앞의 게시글 본문."""
    return raw_text.split("\n[첨부파일: ", 1)[0]


def attachment_links(html: str, page_url: str) -> list[tuple[str, str]]:
    """입력: 상세 페이지 HTML·주소, 출력: 읽을 수 있는 첨부의 (파일 이름, 다운로드 주소) 목록."""
    found: list[tuple[str, str]] = []
    seen: set[str] = set()
    for anchor in BeautifulSoup(html, "html.parser").select(f'a[href*="{DOWNLOAD_PATH}"]'):
        name = " ".join(anchor.get_text(" ", strip=True).split())
        url = urljoin(page_url, str(anchor.get("href")))
        if url in seen or not name.lower().endswith(READABLE_EXTENSIONS):
            continue
        seen.add(url)
        found.append((name, url))
    return found[:MAX_ATTACHMENTS]


async def fetch_attachment_text(client: httpx.AsyncClient, links: list[tuple[str, str]]) -> str:
    """입력: HTTP 클라이언트·첨부 목록, 출력: 파일별 머리말을 붙인 첨부 텍스트; 실패한 파일은 건너뛴다."""
    sections: list[str] = []
    for name, url in links:
        try:
            # 학교 밖 주소(외부 드라이브 링크, 다른 사이트로의 리다이렉트)는 받지 않고 건너뛴다.
            ensure_school_url(url)
            response = await client.get(url, follow_redirects=True)
            ensure_school_url(str(response.url))
            response.raise_for_status()
            if len(response.content) > MAX_BYTES:
                continue
            text = extract_text(name, response.content)
        except Exception:
            continue
        if text:
            sections.append(f"{ATTACHMENT_HEADER.format(name=name)}\n{text[:MAX_CHARS_PER_FILE]}")
    return "\n\n".join(sections)


def extract_text(name: str, data: bytes) -> str:
    """입력: 파일 이름·내용, 출력: 줄 단위로 정리한 텍스트; 지원하지 않는 형식이면 빈 문자열."""
    lower = name.lower()
    if lower.endswith(".hwpx"):
        text = _zip_xml_text(data, r"Contents/section\d+\.xml", "hp:p", "hp:t")
    elif lower.endswith(".docx"):
        text = _zip_xml_text(data, r"word/document\.xml", "w:p", "w:t")
    elif lower.endswith(".pdf"):
        text = _pdf_text(data)
    elif lower.endswith(".hwp"):
        text = _hwp_text(data)
    else:
        return ""
    # 깨진 문서의 짝 없는 서로게이트가 DB 저장(UTF-8)에서 터지지 않게 걸러 낸다.
    text = text.encode("utf-8", errors="ignore").decode("utf-8")
    lines = (" ".join(line.split()) for line in text.splitlines())
    return "\n".join(line for line in lines if line)


def _zip_xml_text(data: bytes, member_pattern: str, paragraph_tag: str, text_tag: str) -> str:
    """입력: zip 형식 문서·본문 XML 경로 패턴·문단/글자 태그, 출력: 문단마다 줄을 바꾼 텍스트.

    HWPX와 DOCX는 모두 zip 안의 XML이라, 문단 태그로 나누고 글자 태그 안 텍스트만 모으면 된다.
    """
    paragraph_re = re.compile(rf"<{paragraph_tag}[\s>].*?</{paragraph_tag}>", re.S)
    text_re = re.compile(rf"<{text_tag}(?:\s[^>]*)?>(.*?)</{text_tag}>", re.S)
    lines: list[str] = []
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        members = sorted(
            (n for n in archive.namelist() if re.fullmatch(member_pattern, n)),
            key=lambda n: int(re.sub(r"\D", "", n) or 0),
        )
        for member in members:
            xml = archive.read(member).decode("utf-8", errors="ignore")
            for paragraph in paragraph_re.findall(xml):
                pieces = (re.sub(r"<[^>]+>", "", piece) for piece in text_re.findall(paragraph))
                lines.append(_unescape("".join(pieces)))
    return "\n".join(lines)


def _unescape(text: str) -> str:
    """입력: XML 텍스트, 출력: 기본 엔터티를 되돌린 문자열."""
    for entity, char in (("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'), ("&apos;", "'"), ("&amp;", "&")):
        text = text.replace(entity, char)
    return text


def _pdf_text(data: bytes) -> str:
    """입력: PDF 내용, 출력: 앞쪽 몇 쪽의 텍스트; 스캔 이미지 PDF는 빈 문자열."""
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    return "\n".join((page.extract_text() or "") for page in reader.pages[:PDF_MAX_PAGES])


def _hwp_text(data: bytes) -> str:
    """입력: HWP 5.x 내용, 출력: 본문 구역의 문단 텍스트.

    HWP는 OLE 복합 문서다. BodyText/SectionN 스트림(대개 zlib 압축)을 풀어
    문단 글자 레코드(HWPTAG_PARA_TEXT)만 골라 UTF-16으로 읽는다.
    """
    import olefile

    with olefile.OleFileIO(io.BytesIO(data)) as ole:
        header = ole.openstream("FileHeader").read()
        compressed = bool(header[36] & 1)
        sections = sorted(
            ("/".join(entry) for entry in ole.listdir() if entry[0] == "BodyText"),
            key=lambda n: int(re.sub(r"\D", "", n) or 0),
        )
        lines: list[str] = []
        for section in sections:
            raw = ole.openstream(section).read()
            if compressed:
                raw = zlib.decompress(raw, -15)
            lines.extend(_hwp_paragraphs(raw))
    return "\n".join(lines)


def _hwp_paragraphs(raw: bytes) -> list[str]:
    """입력: 압축을 푼 본문 구역, 출력: 문단 글자 레코드마다 한 줄씩."""
    paragraphs: list[str] = []
    offset = 0
    while offset + 4 <= len(raw):
        (head,) = struct.unpack_from("<I", raw, offset)
        offset += 4
        tag, size = head & 0x3FF, (head >> 20) & 0xFFF
        if size == 0xFFF:
            (size,) = struct.unpack_from("<I", raw, offset)
            offset += 4
        if tag == HWPTAG_PARA_TEXT:
            paragraphs.append(_hwp_chars(raw[offset : offset + size]))
        offset += size
    return paragraphs


def _hwp_chars(record: bytes) -> str:
    """입력: 문단 글자 레코드, 출력: 컨트롤 문자를 걷어 낸 문자열(탭은 공백으로).

    한자·이모지 같은 글자는 UTF-16 두 칸(서로게이트 쌍)이라, 글자 단위로 chr()하지 않고
    남길 칸만 모아 한 번에 디코딩한다.
    """
    kept = bytearray()
    index = 0
    count = len(record) // 2
    while index < count:
        (code,) = struct.unpack_from("<H", record, index * 2)
        if code >= 32:
            kept += record[index * 2 : index * 2 + 2]
            index += 1
        elif code in HWP_WIDE_CONTROLS:
            if code == 9:
                kept += b" \x00"
            index += 8
        else:
            index += 1
    return kept.decode("utf-16-le", errors="ignore")
