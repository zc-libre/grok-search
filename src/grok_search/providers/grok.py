import httpx
import json
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import List, Optional
from tenacity import AsyncRetrying, retry_if_exception, stop_after_attempt, wait_random_exponential
from tenacity.wait import wait_base
from zoneinfo import ZoneInfo
from .base import BaseSearchProvider, SearchResult
from ..utils import search_prompt, fetch_prompt, url_describe_prompt, rank_sources_prompt
from ..logger import log_info
from ..config import config


def get_local_time_info() -> str:
    """获取本地时间信息，用于注入到搜索查询中"""
    try:
        # 尝试获取系统本地时区
        local_tz = datetime.now().astimezone().tzinfo
        local_now = datetime.now(local_tz)
    except Exception:
        # 降级使用 UTC
        local_now = datetime.now(timezone.utc)

    # 格式化时间信息
    weekdays_cn = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
    weekday = weekdays_cn[local_now.weekday()]

    return (
        f"[Current Time Context]\n"
        f"- Date: {local_now.strftime('%Y-%m-%d')} ({weekday})\n"
        f"- Time: {local_now.strftime('%H:%M:%S')}\n"
        f"- Timezone: {local_now.tzname() or 'Local'}\n"
    )


def _needs_time_context(query: str) -> bool:
    """检查查询是否需要时间上下文"""
    # 中文时间相关关键词
    cn_keywords = [
        "当前", "现在", "今天", "明天", "昨天",
        "本周", "上周", "下周", "这周",
        "本月", "上月", "下月", "这个月",
        "今年", "去年", "明年",
        "最新", "最近", "近期", "刚刚", "刚才",
        "实时", "即时", "目前",
    ]
    # 英文时间相关关键词
    en_keywords = [
        "current", "now", "today", "tomorrow", "yesterday",
        "this week", "last week", "next week",
        "this month", "last month", "next month",
        "this year", "last year", "next year",
        "latest", "recent", "recently", "just now",
        "real-time", "realtime", "up-to-date",
    ]

    query_lower = query.lower()

    for keyword in cn_keywords:
        if keyword in query:
            return True

    for keyword in en_keywords:
        if keyword in query_lower:
            return True

    return False

RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}


def _is_retryable_exception(exc) -> bool:
    """检查异常是否可重试"""
    if isinstance(exc, (httpx.TimeoutException, httpx.NetworkError, httpx.ConnectError, httpx.RemoteProtocolError)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in RETRYABLE_STATUS_CODES
    return False


class _WaitWithRetryAfter(wait_base):
    """等待策略：优先使用 Retry-After 头，否则使用指数退避"""

    def __init__(self, multiplier: float, max_wait: int):
        self._base_wait = wait_random_exponential(multiplier=multiplier, max=max_wait)
        self._protocol_error_base = 3.0

    def __call__(self, retry_state):
        if retry_state.outcome and retry_state.outcome.failed:
            exc = retry_state.outcome.exception()
            if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 429:
                retry_after = self._parse_retry_after(exc.response)
                if retry_after is not None:
                    return retry_after
            if isinstance(exc, httpx.RemoteProtocolError):
                return self._base_wait(retry_state) + self._protocol_error_base
        return self._base_wait(retry_state)

    def _parse_retry_after(self, response: httpx.Response) -> Optional[float]:
        """解析 Retry-After 头（支持秒数或 HTTP 日期格式）"""
        header = response.headers.get("Retry-After")
        if not header:
            return None
        header = header.strip()

        if header.isdigit():
            return float(header)

        try:
            retry_dt = parsedate_to_datetime(header)
            if retry_dt.tzinfo is None:
                retry_dt = retry_dt.replace(tzinfo=timezone.utc)
            delay = (retry_dt - datetime.now(timezone.utc)).total_seconds()
            return max(0.0, delay)
        except (TypeError, ValueError):
            return None


class GrokSearchProvider(BaseSearchProvider):
    def __init__(self, api_url: str, api_key: str, model: str = "grok-4-fast", api_mode: str = "chat", reasoning_effort: str = ""):
        super().__init__(api_url, api_key)
        self.model = model
        self.api_mode = api_mode
        self.reasoning_effort = reasoning_effort

    def get_provider_name(self) -> str:
        return "Grok"

    def _build_payload(self, system_content: str, user_content: str, tools: list[dict] | None = None) -> dict:
        if self.api_mode == "responses":
            payload = {
                "model": self.model,
                "input": [
                    {"role": "system", "content": system_content},
                    {"role": "user", "content": user_content},
                ],
                "stream": True,
                "store": False,
            }
            if tools:
                payload["tools"] = tools
            if self.reasoning_effort and self.reasoning_effort in ("low", "medium", "high", "xhigh"):
                payload["reasoning"] = {"effort": self.reasoning_effort}
        else:
            payload = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_content},
                    {"role": "user", "content": user_content},
                ],
                "stream": True,
            }
        return payload

    def _get_search_tools(self, platform: str = "", x_search_opts: dict | None = None) -> list[dict]:
        tools = [{"type": "web_search"}]
        # 有 x_search 参数时始终加入，否则仅在 platform 为 Twitter/X 时加入
        need_x_search = bool(x_search_opts) or (platform and platform.lower() in ("twitter", "x", "x.com"))
        if need_x_search:
            x_tool: dict = {"type": "x_search"}
            if x_search_opts:
                for key in ("allowed_x_handles", "excluded_x_handles", "from_date", "to_date",
                            "enable_image_understanding", "enable_video_understanding"):
                    if key in x_search_opts and x_search_opts[key] is not None:
                        x_tool[key] = x_search_opts[key]
            tools.append(x_tool)
        return tools

    async def search(self, query: str, platform: str = "", min_results: int = 3, max_results: int = 10,
                     x_search_opts: dict | None = None, ctx=None) -> List[SearchResult]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        platform_prompt = ""

        if platform:
            platform_prompt = "\n\nYou should search the web for the information you need, and focus on these platform: " + platform + "\n"

        time_context = get_local_time_info() + "\n"
        user_content = time_context + query + platform_prompt

        tools = self._get_search_tools(platform, x_search_opts) if self.api_mode == "responses" else None
        payload = self._build_payload(search_prompt, user_content, tools)

        await log_info(ctx, f"platform_prompt: {query + platform_prompt}", config.debug_enabled)

        return await self._execute_stream_with_retry(headers, payload, ctx)

    async def fetch(self, url: str, ctx=None) -> str:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = self._build_payload(fetch_prompt, url + "\n获取该网页内容并返回其结构化Markdown格式")
        return await self._execute_stream_with_retry(headers, payload, ctx)

    async def _parse_streaming_response(self, response, ctx=None) -> str:
        content = ""
        full_body_buffer = [] 
        
        async for line in response.aiter_lines():
            line = line.strip()
            if not line:
                continue
            
            full_body_buffer.append(line)

            # 兼容 "data: {...}" 和 "data:{...}" 两种 SSE 格式
            if line.startswith("data:"):
                if line in ("data: [DONE]", "data:[DONE]"):
                    continue
                try:
                    # 去掉 "data:" 前缀，并去除可能的空格
                    json_str = line[5:].lstrip()
                    data = json.loads(json_str)
                    choices = data.get("choices", [])
                    if choices and len(choices) > 0:
                        delta = choices[0].get("delta", {})
                        if "content" in delta:
                            content += delta["content"]
                except (json.JSONDecodeError, IndexError):
                    continue
                
        if not content and full_body_buffer:
            try:
                full_text = "".join(full_body_buffer)
                data = json.loads(full_text)
                if "choices" in data and len(data["choices"]) > 0:
                    message = data["choices"][0].get("message", {})
                    content = message.get("content", "")
            except json.JSONDecodeError:
                pass
        
        await log_info(ctx, f"content: {content}", config.debug_enabled)

        return content

    @staticmethod
    def _extract_responses_text(data: dict) -> str:
        """从 Responses API 响应体中提取文本，兼容 output[] 和 choices[] 两种格式"""
        text = ""
        # 优先：output[].content[].text（官方 Responses 格式）
        for item in data.get("output", []):
            if item.get("type") == "message":
                for part in item.get("content", []):
                    if part.get("type") == "output_text":
                        text += part.get("text", "")
        if text:
            return text
        # 兜底：choices[].message.content（部分响应兼容 Chat 格式）
        for choice in data.get("choices", []):
            msg = choice.get("message", {})
            if msg.get("content"):
                text += msg["content"]
        return text

    async def _parse_responses_streaming(self, response, ctx=None) -> str:
        """解析 Responses API 的 SSE 流式响应"""
        content = ""
        full_body_buffer = []

        async for line in response.aiter_lines():
            line = line.strip()
            if not line or line.startswith("event:"):
                continue

            full_body_buffer.append(line)

            if line.startswith("data:"):
                json_str = line[5:].lstrip()
                if json_str in ("[DONE]", ""):
                    continue
                try:
                    data = json.loads(json_str)
                    event_type = data.get("type", "")

                    if event_type == "response.output_text.delta":
                        content += data.get("delta", "")
                    elif event_type == "response.output_text.done":
                        if not content:
                            content = data.get("text", "")
                    elif event_type in ("response.completed", "response.done"):
                        # 从完整响应中提取文本（兜底）
                        if not content:
                            resp = data.get("response", {})
                            content = self._extract_responses_text(resp)
                except (json.JSONDecodeError, IndexError):
                    continue

        # 兜底：尝试作为非流式响应解析
        if not content and full_body_buffer:
            try:
                data_lines = [l[5:].lstrip() if l.startswith("data:") else l for l in full_body_buffer]
                full_text = "".join(data_lines)
                data = json.loads(full_text)
                content = self._extract_responses_text(data)
            except json.JSONDecodeError:
                pass

        await log_info(ctx, f"content: {content}", config.debug_enabled)
        return content

    async def _execute_stream_with_retry(self, headers: dict, payload: dict, ctx=None) -> str:
        """执行带重试机制的流式 HTTP 请求"""
        endpoint = "/responses" if self.api_mode == "responses" else "/chat/completions"
        parser = self._parse_responses_streaming if self.api_mode == "responses" else self._parse_streaming_response
        timeout = httpx.Timeout(connect=6.0, read=120.0, write=10.0, pool=None)

        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(config.retry_max_attempts + 1),
                wait=_WaitWithRetryAfter(config.retry_multiplier, config.retry_max_wait),
                retry=retry_if_exception(_is_retryable_exception),
                reraise=True,
            ):
                with attempt:
                    async with client.stream(
                        "POST",
                        f"{self.api_url}{endpoint}",
                        headers=headers,
                        json=payload,
                    ) as response:
                        response.raise_for_status()
                        return await parser(response, ctx)

    async def describe_url(self, url: str, ctx=None) -> dict:
        """让 Grok 阅读单个 URL 并返回 title + extracts"""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = self._build_payload(url_describe_prompt, url)
        result = await self._execute_stream_with_retry(headers, payload, ctx)
        title, extracts = url, ""
        for line in result.strip().splitlines():
            if line.startswith("Title:"):
                title = line[6:].strip() or url
            elif line.startswith("Extracts:"):
                extracts = line[9:].strip()
        return {"title": title, "extracts": extracts, "url": url}

    async def rank_sources(self, query: str, sources_text: str, total: int, ctx=None) -> list[int]:
        """让 Grok 按查询相关度对信源排序，返回排序后的序号列表"""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = self._build_payload(rank_sources_prompt, f"Query: {query}\n\n{sources_text}")
        result = await self._execute_stream_with_retry(headers, payload, ctx)
        order: list[int] = []
        seen: set[int] = set()
        for token in result.strip().split():
            try:
                n = int(token)
                if 1 <= n <= total and n not in seen:
                    seen.add(n)
                    order.append(n)
            except ValueError:
                continue
        # 补齐遗漏的序号
        for i in range(1, total + 1):
            if i not in seen:
                order.append(i)
        return order
