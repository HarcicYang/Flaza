"""消息媒体文件的本地磁盘缓存。"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import logging
import mimetypes
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse
from urllib.request import Request, urlopen

from flaza.core.models import (
    AudioElement,
    FileElement,
    ImageElement,
    MarketFaceElement,
    Message,
    VideoElement,
)

logger = logging.getLogger(__name__)

DEFAULT_MAX_TOTAL_BYTES = 2 * 1024 * 1024 * 1024
DEFAULT_MAX_FILE_BYTES = 512 * 1024 * 1024
DEFAULT_TIMEOUT_SECONDS = 60.0
DEFAULT_CONCURRENCY = 2

_USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Flaza/0.1"
_FALLBACK_EXTENSION = {
    "image": ".img",
    "market_face": ".png",
    "audio": ".amr",
    "video": ".mp4",
    "file": ".bin",
}


@dataclass(frozen=True)
class _MediaJob:
    index: int
    kind: str
    url: str
    key: str
    cached_path: str
    preferred_name: str = ""


class MediaCache:
    """下载消息中的媒体到本地目录，供 UI 以 file:// 方式读取。"""

    def __init__(
        self,
        root: str | Path,
        *,
        max_total_bytes: int = DEFAULT_MAX_TOTAL_BYTES,
        max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        concurrency: int = DEFAULT_CONCURRENCY,
    ) -> None:
        self._root = Path(root).resolve()
        self._max_total_bytes = max_total_bytes
        self._max_file_bytes = max_file_bytes
        self._timeout_seconds = timeout_seconds
        self._semaphore = asyncio.Semaphore(max(1, concurrency))
        self._inflight: dict[str, asyncio.Task[str | None]] = {}

    def has_cacheable_media(self, message: Message) -> bool:
        """消息是否包含可下载到本地缓存的媒体元素。"""
        return bool(self._jobs_for(message))

    async def cache_message(self, message: Message) -> Message:
        """下载消息中缺失的媒体，返回带 cached_path 的新消息模型。

        下载失败时返回未修改的原始元素，调用方可以安全地继续使用远程 URL。
        """
        jobs = self._jobs_for(message)
        if not jobs:
            return message

        paths = await asyncio.gather(*(self._cache_job(job) for job in jobs))
        elements = list(message.elements)
        for job, path in zip(jobs, paths, strict=True):
            if path is None:
                continue
            element = elements[job.index]
            if getattr(element, "cached_path", "") == path:
                continue
            elements[job.index] = element.model_copy(update={"cached_path": path})
        return message.model_copy(update={"elements": elements})

    def _jobs_for(self, message: Message) -> list[_MediaJob]:
        chat_key = message.chat.key
        jobs: list[_MediaJob] = []
        for index, element in enumerate(message.elements):
            if isinstance(element, ImageElement) and element.url:
                key = self._media_key("image", element.md5, element.size, chat_key, element.url, fallback=element.url)
                jobs.append(_MediaJob(index, "image", element.url, key, element.cached_path))
            elif isinstance(element, MarketFaceElement) and element.face_id:
                key = f"market_face:{element.face_id.hex()}"
                jobs.append(
                    _MediaJob(
                        index,
                        "market_face",
                        element.url,
                        key,
                        element.cached_path,
                        preferred_name=element.name,
                    )
                )
            elif isinstance(element, AudioElement) and element.url:
                key = self._media_key(
                    "audio",
                    element.md5,
                    element.size,
                    chat_key,
                    element.file_key or element.url,
                    fallback=element.url,
                )
                jobs.append(_MediaJob(index, "audio", element.url, key, element.cached_path))
            elif isinstance(element, VideoElement) and element.url:
                key = self._media_key(
                    "video",
                    element.md5,
                    element.size,
                    chat_key,
                    element.file_key or element.url,
                    fallback=element.url,
                )
                jobs.append(
                    _MediaJob(
                        index,
                        "video",
                        element.url,
                        key,
                        element.cached_path,
                        preferred_name=element.name,
                    )
                )
            elif isinstance(element, FileElement) and element.file_url:
                identity = element.file_id or element.file_uuid or element.file_url or ""
                key = self._media_key(
                    "file",
                    element.md5,
                    element.file_size,
                    chat_key,
                    identity,
                    fallback=element.file_url or "",
                )
                jobs.append(
                    _MediaJob(
                        index,
                        "file",
                        element.file_url,
                        key,
                        element.cached_path,
                        preferred_name=element.file_name,
                    )
                )
        return jobs

    @staticmethod
    def _media_key(
        kind: str,
        md5: bytes,
        size: int,
        chat_key: str,
        identity: str,
        *,
        fallback: str,
    ) -> str:
        if md5:
            return f"{kind}:{md5.hex()}:{size}"
        if identity:
            return f"{kind}:{chat_key}:{identity}"
        return f"{kind}:url:{hashlib.sha256(fallback.encode()).hexdigest()}"

    async def _cache_job(self, job: _MediaJob) -> str | None:
        existing = await asyncio.to_thread(self._find_existing, job)
        if existing is not None:
            return existing

        task = self._inflight.get(job.key)
        if task is None:
            task = asyncio.create_task(self._download_job(job))
            self._inflight[job.key] = task
            task.add_done_callback(lambda done, key=job.key: self._discard_inflight(key, done))
        return await asyncio.shield(task)

    def _discard_inflight(self, key: str, task: asyncio.Task[str | None]) -> None:
        if self._inflight.get(key) is task:
            self._inflight.pop(key, None)

    async def _download_job(self, job: _MediaJob) -> str | None:
        async with self._semaphore:
            try:
                path = await asyncio.to_thread(self._download_sync, job)
                if path is not None:
                    await asyncio.to_thread(self._trim_if_needed)
                return path
            except Exception:
                logger.debug("媒体缓存下载失败: kind=%s url=%s", job.kind, job.url, exc_info=True)
                return None

    def _find_existing(self, job: _MediaJob) -> str | None:
        if job.cached_path:
            cached = Path(job.cached_path)
            if cached.is_file():
                return str(cached)

        directory, digest = self._cache_dir(job.kind, job.key)
        if not directory.is_dir():
            return None
        for candidate in sorted(directory.glob(f"{digest}.*")):
            if candidate.is_file() and not candidate.name.startswith("."):
                return str(candidate)
        return None

    def _download_sync(self, job: _MediaJob) -> str | None:
        directory, digest = self._cache_dir(job.kind, job.key)
        directory.mkdir(parents=True, exist_ok=True)
        temp_path = directory / f".{digest}.{os.getpid()}.part"

        request = Request(job.url, headers={"User-Agent": _USER_AGENT})
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                content_type = response.headers.get_content_type()
                content_length = response.headers.get("Content-Length")
                if content_length and int(content_length) > self._max_file_bytes:
                    logger.debug("媒体超过单文件缓存上限，跳过: url=%s size=%s", job.url, content_length)
                    return None

                size = 0
                with temp_path.open("wb") as file:
                    while True:
                        chunk = response.read(min(64 * 1024, self._max_file_bytes - size + 1))
                        if not chunk:
                            break
                        size += len(chunk)
                        if size > self._max_file_bytes:
                            raise _FileTooLarge(job.url, size)
                        file.write(chunk)

            extension = _extension_for(job, content_type)
            final_path = directory / f"{digest}{extension}"
            os.replace(temp_path, final_path)
            return str(final_path)
        except Exception:
            with contextlib.suppress(FileNotFoundError):
                temp_path.unlink()
            raise

    def _trim_if_needed(self) -> None:
        if self._max_total_bytes <= 0:
            return
        files: list[tuple[float, int, Path]] = []
        total = 0
        for path in self._root.rglob("*"):
            if not path.is_file() or path.name.startswith("."):
                continue
            stat = path.stat()
            files.append((stat.st_mtime, stat.st_size, path))
            total += stat.st_size

        files.sort(key=_lru_sort_key)
        for _mtime, size, path in files:
            if total <= self._max_total_bytes:
                break
            with contextlib.suppress(FileNotFoundError):
                path.unlink()
            total -= size

    def _cache_dir(self, kind: str, key: str) -> tuple[Path, str]:
        digest = hashlib.sha256(key.encode()).hexdigest()
        return self._root / kind / digest[:2], digest


def _lru_sort_key(item: tuple[float, int, Path]) -> tuple[float, str]:
    return item[0], str(item[2])


class _FileTooLarge(Exception):
    """单文件超过缓存上限。"""

    def __init__(self, url: str, size: int) -> None:
        super().__init__(f"媒体文件超过缓存上限: url={url} size={size}")


def _extension_for(job: _MediaJob, content_type: str) -> str:
    if job.kind == "market_face":
        return ".png"

    if job.preferred_name:
        extension = Path(job.preferred_name).suffix
        if extension:
            return extension.lower()

    path = unquote(urlparse(job.url).path)
    extension = Path(path).suffix
    if extension:
        return extension.lower()

    if content_type:
        guessed = mimetypes.guess_extension(content_type)
        if guessed:
            return guessed

    return _FALLBACK_EXTENSION.get(job.kind, ".bin")
