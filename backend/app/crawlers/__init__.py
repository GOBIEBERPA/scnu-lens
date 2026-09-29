from app.crawlers.dataq import DataqExamCrawler
from app.crawlers.exam import QnetExamCrawler
from app.crawlers.kosaf import KosafScholarshipCrawler
from app.crawlers.kstartup import KStartupCrawler
from app.crawlers.manual import ManualExamCrawler
from app.crawlers.scnu import CRAWLER_REGISTRY as _SCNU_REGISTRY, default_sources

# 수집 대상은 순천대 게시판, 공식 발급 API(공공데이터포털), 관리자가 직접 적은 일정뿐이다.
# 다른 기관·민간 사이트는 허락 없이 수집하지 않는다.
CRAWLER_REGISTRY = {
    **_SCNU_REGISTRY,
    "exam_qnet": QnetExamCrawler,
    "exam_dataq": DataqExamCrawler,
    "contest_kstartup": KStartupCrawler,
    "scholar_kosaf": KosafScholarshipCrawler,
    "exam_manual": ManualExamCrawler,
}

__all__ = ["CRAWLER_REGISTRY", "default_sources"]
