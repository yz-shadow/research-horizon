from __future__ import annotations

from io import BytesIO
from collections import OrderedDict
from copy import deepcopy
from email.utils import parsedate_to_datetime
import math
import re
import threading
import time
import xml.etree.ElementTree as ET

from pypdf import PdfReader
from pypdf.errors import PdfReadError
import requests


ARXIV_API = "https://export.arxiv.org/api/query"
ATOM = "{http://www.w3.org/2005/Atom}"
_ARXIV_LOCK = threading.Lock()
_ARXIV_CACHE: OrderedDict = OrderedDict()
_NEXT_REQUEST_AT = 0.0
_BLOCKED_UNTIL = 0.0
_CACHE_TTL = 3600
_CACHE_ENTRIES = 128
_MIN_INTERVAL = 3.1
_ATTEMPTS = 3
_MAX_AUTO_WAIT = 30


class ArxivLoadError(ValueError):
    """An actionable arXiv error suitable for display in the application."""


def _retry_after(value: str | None) -> float:
    if not value:
        return 0
    try:
        seconds = float(value)
    except ValueError:
        try:
            seconds = parsedate_to_datetime(value).timestamp() - time.time()
        except (ValueError, TypeError, OverflowError):
            return 0
    return max(0, seconds) if math.isfinite(seconds) else 0


def _rate_limit_message(seconds: float) -> str:
    return (
        f"arXiv 暂时限制访问（429），请至少等待 {max(1, math.ceil(seconds))} 秒后再试。"
        "请勿连续点击载入；共享网络出口或服务端繁忙也可能触发限流。"
        "可以先使用“上传 PDF”或“示例数据”；按 ID 载入也使用同一接口。"
    )


def _request_arxiv(params: dict) -> list[dict]:
    """Serialize search/ID requests and retries across this server's sessions.

    Successes are cached for one hour; errors never become search results.
    A shared cooldown prevents another query from immediately retrying a 429.
    """
    global _NEXT_REQUEST_AT, _BLOCKED_UNTIL
    key = tuple(sorted((name, str(value)) for name, value in params.items()))
    with _ARXIV_LOCK:
        now = time.monotonic()
        for old_key, (expires, _) in list(_ARXIV_CACHE.items()):
            if expires <= now:
                del _ARXIV_CACHE[old_key]
        if key in _ARXIV_CACHE:
            _ARXIV_CACHE.move_to_end(key)
            return deepcopy(_ARXIV_CACHE[key][1])
        if _BLOCKED_UNTIL > now:
            raise ArxivLoadError(_rate_limit_message(_BLOCKED_UNTIL - now))

        for attempt in range(_ATTEMPTS):
            wait = max(_NEXT_REQUEST_AT, _BLOCKED_UNTIL) - time.monotonic()
            if wait > _MAX_AUTO_WAIT:
                if _BLOCKED_UNTIL > time.monotonic():
                    raise ArxivLoadError(_rate_limit_message(wait))
                raise ArxivLoadError(f"arXiv 服务暂时繁忙，请至少等待 {math.ceil(wait)} 秒后再试。")
            if wait > 0:
                time.sleep(wait)
            _NEXT_REQUEST_AT = time.monotonic() + _MIN_INTERVAL
            try:
                with requests.get(
                    ARXIV_API, params=params, timeout=(10, 35),
                    headers={"User-Agent": "ResearchHorizon/0.2 (educational prototype)",
                             "Accept": "application/atom+xml"},
                ) as response:
                    status = response.status_code
                    if status in {429, 500, 502, 503, 504}:
                        delay = max(_retry_after(response.headers.get("Retry-After")),
                                    (10 if status == 429 else 3.1) * (2 ** attempt))
                        _NEXT_REQUEST_AT = max(_NEXT_REQUEST_AT, time.monotonic() + delay)
                        if status == 429:
                            if attempt == _ATTEMPTS - 1:
                                delay = max(delay, 60)
                            _BLOCKED_UNTIL = time.monotonic() + delay
                        if attempt < _ATTEMPTS - 1 and delay <= _MAX_AUTO_WAIT:
                            continue
                        if status == 429:
                            raise ArxivLoadError(_rate_limit_message(delay))
                        raise ArxivLoadError("arXiv 服务暂时繁忙，已停止自动重试。请稍后再试，或上传 PDF。")
                    response.raise_for_status()
                    papers = _parse_feed(response.content)
                _ARXIV_CACHE[key] = (time.monotonic() + _CACHE_TTL, deepcopy(papers))
                while len(_ARXIV_CACHE) > _CACHE_ENTRIES:
                    _ARXIV_CACHE.popitem(last=False)
                return papers
            except (requests.Timeout, requests.ConnectionError) as exc:
                if attempt == _ATTEMPTS - 1:
                    raise ArxivLoadError("无法连接 arXiv 或请求超时，已停止自动重试。请检查网络，或上传 PDF。") from exc
                _NEXT_REQUEST_AT = max(_NEXT_REQUEST_AT, time.monotonic() + 3.1 * (2 ** attempt))
            except requests.HTTPError as exc:
                raise ArxivLoadError(f"arXiv 请求失败（HTTP {exc.response.status_code}），请稍后重试。") from exc


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _parse_feed(content: bytes) -> list[dict]:
    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        raise ArxivLoadError("arXiv 返回了无法解析的数据，请稍后重试。") from exc
    if root.tag != f"{ATOM}feed":
        raise ArxivLoadError("arXiv 未返回预期的论文数据，请稍后重试。")
    papers = []
    for entry in root.findall(f"{ATOM}entry"):
        title = _clean(entry.findtext(f"{ATOM}title", default=""))
        abstract = _clean(entry.findtext(f"{ATOM}summary", default=""))
        url = _clean(entry.findtext(f"{ATOM}id", default=""))
        if "/api/errors" in url:
            raise ArxivLoadError(f"arXiv 未能完成查询：{abstract[:250]}")
        if not title or not abstract:
            continue
        papers.append({
            "id": url.rsplit("/", 1)[-1],
            "title": title,
            "url": url,
            "published": entry.findtext(f"{ATOM}published", default="")[:10],
            "source": "arXiv 摘要",
            "text": f"{title}\n\n{abstract}",
        })
    return papers


def search_arxiv(query: str, limit: int = 12) -> list[dict]:
    query = _clean(query)
    if not query:
        raise ValueError("请填写研究主题。")
    terms = re.findall(r"[\w-]+", query, flags=re.UNICODE)[:12]
    if not terms:
        raise ValueError("研究主题需要包含可检索的词语。")
    search_query = " AND ".join(f"all:{term}" for term in terms)
    return _request_arxiv(
        {"search_query": search_query, "start": 0, "max_results": max(1, min(limit, 30)),
                "sortBy": "relevance", "sortOrder": "descending"},
    )


def fetch_arxiv_ids(raw_ids: str) -> list[dict]:
    ids = [part.strip() for part in re.split(r"[,\s]+", raw_ids) if part.strip()]
    ids = [re.sub(r"^https?://arxiv\.org/(?:abs|pdf)/", "", value).removesuffix(".pdf") for value in ids]
    if not ids or len(ids) > 30 or any(not re.fullmatch(r"[A-Za-z0-9.\-]+(?:v\d+)?", x) for x in ids):
        raise ValueError("请输入 1–30 个有效的 arXiv ID，以逗号或空格分隔。")
    return _request_arxiv({"id_list": ",".join(ids), "max_results": len(ids)})


def read_pdf(name: str, content: bytes) -> dict:
    if len(content) > 20 * 1024 * 1024:
        raise ValueError(f"{name} 超过 20 MB。")
    try:
        reader = PdfReader(BytesIO(content))
        pages = [page.extract_text() or "" for page in reader.pages[:20]]
    except (PdfReadError, ValueError, OSError) as exc:
        raise ValueError(f"{name} 无法解析为可读取的 PDF：{exc}") from exc
    text = "\n\n".join(pages).strip()
    if len(text) < 100:
        raise ValueError(f"{name} 没有足够的可提取文字；扫描版请先 OCR。")
    return {
        "id": f"pdf:{name}",
        "title": name.rsplit(".", 1)[0],
        "url": "",
        "published": "",
        "source": "上传 PDF，前 20 页",
        "text": text[:18000],
    }
