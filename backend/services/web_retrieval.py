from __future__ import annotations

import json
import re
import subprocess
import tempfile
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import httpx
from bs4 import BeautifulSoup

from ..config import Settings
from ..exceptions import ValidationError
from .browser_sessions import BrowserSessionManager
from .utils import iso_now, trim_output


class WebRetrievalService:
    """Retrieves text and evidence from ordinary, rendered, and document URLs."""

    USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Vogi/4.0"

    def __init__(self, settings: Settings, browser_sessions: BrowserSessionManager) -> None:
        self.settings = settings
        self.browser_sessions = browser_sessions

    async def search(self, args: dict[str, Any]) -> dict[str, Any]:
        query = str(args.get("query") or "").strip()
        if not query:
            raise ValidationError("web_search requires query.")
        max_results = min(max(int(args.get("max_results") or 6), 1), 10)
        search_url = "https://html.duckduckgo.com/html/"
        http_error = ""
        try:
            async with httpx.AsyncClient(timeout=25, follow_redirects=True, headers={"User-Agent": self.USER_AGENT}) as client:
                response = await client.get(search_url, params={"q": query})
            results = self.parse_search_results(response.text, max_results)
            challenged = self.search_page_blocked(response.text)
            if results and not challenged:
                return {
                    "query": query,
                    "provider": "duckduckgo",
                    "retrievalMode": "http",
                    "status": "ok",
                    "statusCode": response.status_code,
                    "results": results,
                    "error": None,
                }
            http_error = "Search returned no usable results." if not challenged else "Search provider presented a blocking/challenge page."
        except Exception as exc:
            http_error = f"HTTP search failed: {trim_output(str(exc), 240)}"

        rendered_url = str(httpx.URL("https://html.duckduckgo.com/html/", params={"q": query}))
        rendered = await self.browser_sessions.render_public(rendered_url)
        if not rendered.get("error"):
            results = self.parse_search_results(str(rendered.get("html") or ""), max_results)
            if results:
                return {
                    "query": query,
                    "provider": "duckduckgo",
                    "retrievalMode": "rendered",
                    "status": "ok",
                    "results": results,
                    "error": None,
                }
        render_error = str(rendered.get("error") or "Rendered search returned no usable results.")
        return {
            "query": query,
            "provider": "duckduckgo",
            "retrievalMode": "http+rendered",
            "status": "failed",
            "results": [],
            "error": f"{http_error} {render_error}".strip(),
        }

    async def browse(self, args: dict[str, Any]) -> dict[str, Any]:
        url = str(args.get("url") or "").strip()
        if not re.match(r"^https?://", url, flags=re.I):
            raise ValidationError("browse_url requires an http or https URL.")
        max_chars = min(max(int(args.get("max_chars") or 12000), 1000), 50000)
        mode = str(args.get("mode") or "auto").lower()
        session = str(args.get("session") or "public").lower()
        if mode not in {"auto", "http", "rendered"}:
            raise ValidationError("browse_url mode must be auto, http, or rendered.")
        if session not in {"public", "authenticated"}:
            raise ValidationError("browse_url session must be public or authenticated.")
        if session == "authenticated":
            return await self.rendered_browse(url, max_chars, authenticated=True)
        if mode == "rendered":
            return await self.rendered_browse(url, max_chars)

        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers={"User-Agent": self.USER_AGENT}) as client:
                response = await client.get(url)
        except Exception as exc:
            if mode == "auto":
                rendered = await self.rendered_browse(url, max_chars)
                if not rendered.get("error"):
                    return rendered
            return self.failure(url, "public", "http", f"HTTP retrieval failed: {trim_output(str(exc), 240)}")

        result = self.extract_response(response, max_chars)
        if mode == "auto" and result["contentType"].startswith("text/html") and self.should_render(result):
            rendered = await self.rendered_browse(str(response.url), max_chars)
            if not rendered.get("error"):
                rendered["httpFallbackReason"] = "Raw page did not expose sufficient readable content."
                return rendered
            result["renderError"] = rendered["error"]
        return result

    def extract_response(self, response: httpx.Response, max_chars: int) -> dict[str, Any]:
        content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
        url = str(response.url)
        if content_type == "application/pdf" or urlparse(url).path.lower().endswith(".pdf"):
            return self.extract_pdf(response.content, url, response.status_code, max_chars)
        if content_type.startswith("image/"):
            return self.extract_image(response.content, url, response.status_code, content_type, max_chars)
        if content_type == "application/json" or content_type.endswith("+json"):
            return self.base_result(url, response.status_code, content_type, "http", "public", trim_output(response.text, max_chars), [], [], "high")
        if content_type.startswith("text/") or "html" in content_type or not content_type:
            return self.extract_html(response.text, url, response.status_code, content_type or "text/html", max_chars, "http", "public")
        return self.failure(url, "public", "http", f"Unsupported content type: {content_type or 'unknown'}", response.status_code, content_type)

    def extract_html(self, html: str, url: str, status_code: int | None, content_type: str, max_chars: int, retrieval_mode: str, session: str) -> dict[str, Any]:
        soup = BeautifulSoup(html, "html.parser")
        title = soup.title.get_text(" ", strip=True) if soup.title else ""
        facts = self.structured_facts(soup)
        links: list[dict[str, str]] = []
        for item in soup.find_all("a", href=True):
            href = str(item.get("href") or "").strip()
            label = re.sub(r"\s+", " ", item.get_text(" ", strip=True))
            if href.startswith("http") and label:
                links.append({"title": label[:160], "url": href})
            if len(links) >= 25:
                break
        for element in soup(["script", "style", "noscript", "svg", "template"]):
            element.decompose()
        main = soup.find("main") or soup.find("article") or soup.body or soup
        readable = re.sub(r"\n{3,}", "\n\n", main.get_text("\n", strip=True))
        confidence = "high" if readable or facts else "low"
        result = self.base_result(url, status_code, content_type, retrieval_mode, session, trim_output(readable, max_chars), facts, links, confidence)
        result["title"] = title
        return result

    async def rendered_browse(self, url: str, max_chars: int, authenticated: bool = False) -> dict[str, Any]:
        session = "authenticated" if authenticated else "public"
        payload = await (self.browser_sessions.read_authenticated(url) if authenticated else self.browser_sessions.render_public(url))
        if payload.get("error"):
            return self.failure(url, session, "rendered", str(payload["error"]))
        html = str(payload.get("html") or "")
        result = self.extract_html(html, str(payload.get("url") or url), payload.get("statusCode"), "text/html", max_chars, "rendered", session)
        visible = str(payload.get("text") or "").strip()
        if visible:
            result["text"] = trim_output(visible, max_chars)
            result["confidence"] = "high"
        if payload.get("title"):
            result["title"] = payload["title"]
        return result

    def extract_pdf(self, data: bytes, url: str, status_code: int | None, max_chars: int) -> dict[str, Any]:
        text = ""
        error = None
        try:
            from pypdf import PdfReader
            reader = PdfReader(BytesIO(data))
            text = "\n\n".join((page.extract_text() or "").strip() for page in reader.pages[:30]).strip()
        except Exception as exc:
            error = f"PDF text extraction failed: {trim_output(str(exc), 200)}"
        mode = "pdf-text"
        if len(text) < 80:
            ocr_text, ocr_error = self.ocr_pdf(data)
            if ocr_text:
                text, mode, error = ocr_text, "pdf-ocr", None
            elif ocr_error:
                error = ocr_error if not error else f"{error} {ocr_error}"
        result = self.base_result(url, status_code, "application/pdf", mode, "public", trim_output(text, max_chars), [], [], "high" if text else "low")
        result["error"] = error
        return result

    def extract_image(self, data: bytes, url: str, status_code: int | None, content_type: str, max_chars: int) -> dict[str, Any]:
        text, error = self.ocr_image(data, suffix=self.image_suffix(content_type))
        result = self.base_result(url, status_code, content_type, "image-ocr", "public", trim_output(text, max_chars), [], [], "medium" if text else "low")
        result["error"] = error
        return result

    def ocr_pdf(self, data: bytes) -> tuple[str, str | None]:
        try:
            import fitz
        except ImportError:
            return "", "OCR for scanned PDFs requires PyMuPDF (`pip install pymupdf`)."
        pages: list[str] = []
        try:
            document = fitz.open(stream=data, filetype="pdf")
            for page in document[:10]:
                pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                text, _ = self.ocr_image(pixmap.tobytes("png"), ".png")
                if text:
                    pages.append(text)
        except Exception as exc:
            return "", f"Could not render scanned PDF for OCR: {trim_output(str(exc), 200)}"
        if pages:
            return "\n\n".join(pages), None
        return "", "No readable text was recovered from the scanned PDF."

    def ocr_image(self, data: bytes, suffix: str = ".png") -> tuple[str, str | None]:
        executable = self.settings.tesseract_path
        if not executable.exists():
            return "", f"OCR is unavailable because Tesseract was not found at {executable}."
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / f"input{suffix}"
            source.write_bytes(data)
            try:
                completed = subprocess.run([str(executable), str(source), "stdout"], capture_output=True, text=True, timeout=45, check=False)
            except Exception as exc:
                return "", f"OCR failed: {trim_output(str(exc), 200)}"
        output = completed.stdout.strip()
        if completed.returncode != 0 and not output:
            return "", f"OCR failed: {trim_output(completed.stderr, 200)}"
        return output, None

    @staticmethod
    def parse_search_results(html: str, max_results: int) -> list[dict[str, Any]]:
        soup = BeautifulSoup(html, "html.parser")
        results: list[dict[str, Any]] = []
        for block in soup.select(".result"):
            link = block.select_one("a.result__a")
            if not link:
                continue
            href = str(link.get("href") or "").replace("&amp;", "&")
            redirect = re.search(r"[?&]uddg=([^&]+)", href)
            clean_url = unquote(redirect.group(1)) if redirect else href
            if not clean_url.startswith("http"):
                continue
            snippet_node = block.select_one(".result__snippet")
            snippet = re.sub(r"\s+", " ", snippet_node.get_text(" ", strip=True)) if snippet_node else ""
            title = re.sub(r"\s+", " ", link.get_text(" ", strip=True))
            results.append({
                "title": title[:200],
                "url": clean_url,
                "snippet": snippet[:400],
                "rank": len(results) + 1,
                "sourceDomain": urlparse(clean_url).netloc,
            })
            if len(results) >= max_results:
                break
        return results

    @staticmethod
    def search_page_blocked(html: str) -> bool:
        lowered = html.lower()
        return any(marker in lowered for marker in ["captcha", "verify you are human", "anomaly-modal", "unusual traffic"])

    @staticmethod
    def structured_facts(soup: BeautifulSoup) -> list[dict[str, Any]]:
        facts: list[dict[str, Any]] = []
        for script in soup.find_all("script", attrs={"type": re.compile("ld\\+json", re.I)}):
            try:
                value = json.loads(script.string or script.get_text() or "")
            except (TypeError, json.JSONDecodeError):
                continue
            items = value if isinstance(value, list) else [value]
            for item in items:
                WebRetrievalService.collect_structured_items(item, facts)
                if len(facts) >= 20:
                    return facts
        meta: dict[str, str] = {}
        for item in soup.find_all("meta"):
            key = item.get("property") or item.get("name")
            content = item.get("content")
            if key and content and str(key).lower() in {"description", "og:title", "og:description", "article:published_time"}:
                meta[str(key)] = str(content)[:500]
        if meta:
            facts.append({"type": "metadata", **meta})
        return facts

    @staticmethod
    def collect_structured_items(value: Any, facts: list[dict[str, Any]]) -> None:
        if isinstance(value, list):
            for item in value:
                WebRetrievalService.collect_structured_items(item, facts)
            return
        if not isinstance(value, dict):
            return
        if "@graph" in value:
            WebRetrievalService.collect_structured_items(value["@graph"], facts)
        kind = value.get("@type")
        if kind:
            compact: dict[str, Any] = {"type": kind}
            for key in ("name", "headline", "datePublished", "dateModified", "description", "url", "price", "lowPrice", "highPrice", "priceCurrency", "availability"):
                if key in value and not isinstance(value[key], (dict, list)):
                    compact[key] = value[key]
            offers = value.get("offers")
            if isinstance(offers, dict):
                compact["offers"] = {key: offers[key] for key in ("price", "lowPrice", "highPrice", "priceCurrency", "availability") if key in offers}
            elif isinstance(offers, list):
                compact["offers"] = [
                    {key: offer[key] for key in ("price", "lowPrice", "highPrice", "priceCurrency", "availability") if key in offer}
                    for offer in offers
                    if isinstance(offer, dict)
                ][:10]
            if len(compact) > 1:
                facts.append(compact)
        for child_key in ("mainEntity", "itemListElement", "offers", "acceptedAnswer"):
            if child_key in value:
                WebRetrievalService.collect_structured_items(value[child_key], facts)

    @staticmethod
    def should_render(result: dict[str, Any]) -> bool:
        text = str(result.get("text") or "").lower()
        return len(text.strip()) < 160 or any(marker in text for marker in ["enable javascript", "javascript is required", "access denied", "verify you are human"])

    @staticmethod
    def image_suffix(content_type: str) -> str:
        return { "image/jpeg": ".jpg", "image/webp": ".webp", "image/gif": ".gif" }.get(content_type, ".png")

    @staticmethod
    def base_result(url: str, status_code: int | None, content_type: str, retrieval_mode: str, session: str, text: str, facts: list[Any], links: list[Any], confidence: str) -> dict[str, Any]:
        return {
            "url": url,
            "title": "",
            "statusCode": status_code,
            "contentType": content_type,
            "retrievalMode": retrieval_mode,
            "session": session,
            "text": text,
            "facts": facts,
            "links": links,
            "extractedAt": iso_now(),
            "confidence": confidence,
            "error": None,
        }

    @staticmethod
    def failure(url: str, session: str, mode: str, error: str, status_code: int | None = None, content_type: str = "") -> dict[str, Any]:
        result = WebRetrievalService.base_result(url, status_code, content_type, mode, session, "", [], [], "low")
        result["error"] = error
        return result
