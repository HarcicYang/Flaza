"""媒体本地缓存服务测试。"""

import asyncio
from pathlib import Path

from flaza.core.models import FriendChat, ImageElement, Message
from flaza.core.services.media_cache import MediaCache


class _HttpFixture:
    def __init__(self) -> None:
        self.request_count = 0
        self._server: asyncio.Server | None = None
        self.port = 0

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    async def start(self) -> "_HttpFixture":
        async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            try:
                request = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=5)
            except (TimeoutError, asyncio.IncompleteReadError):
                writer.close()
                return
            self.request_count += 1
            request_line = request.split(b"\r\n", 1)[0].decode()
            path = request_line.split(" ")[1]

            body = b"cached-image-bytes"
            content_type = "application/octet-stream"
            status = "200 OK"
            if path == "/pic.png":
                content_type = "image/png"
            elif path == "/file.bin":
                body = b"x" * 16
                content_type = "application/octet-stream"
            else:
                status = "404 Not Found"
                body = b"missing"

            writer.write(
                (
                    f"HTTP/1.1 {status}\r\n"
                    f"Content-Type: {content_type}\r\n"
                    f"Content-Length: {len(body)}\r\n"
                    "Connection: close\r\n"
                    "\r\n"
                ).encode()
                + body
            )
            await writer.drain()
            writer.close()
            await writer.wait_closed()

        self._server = await asyncio.start_server(handle, "127.0.0.1", 0)
        self.port = int(self._server.sockets[0].getsockname()[1])
        return self

    async def close(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()


def _image_message(url: str, md5: bytes = b"image-md5", cached_path: str = "") -> Message:
    return Message(
        chat=FriendChat(uid="u_1", uin=10001),
        sender_uin=10001,
        sender_uid="u_1",
        seq=1,
        timestamp=100,
        elements=[
            ImageElement(
                url=url,
                md5=md5,
                size=18,
                width=640,
                height=480,
                cached_path=cached_path,
            )
        ],
    )


def test_cache_message_downloads_and_reuses_local_file(tmp_path: Path) -> None:
    async def scenario() -> None:
        http = await _HttpFixture().start()
        try:
            cache = MediaCache(tmp_path)
            message = _image_message(f"{http.base_url}/pic.png")
            assert cache.has_cacheable_media(message) is True

            cached = await cache.cache_message(message)
            element = cached.elements[0]
            assert isinstance(element, ImageElement)
            assert element.cached_path
            assert Path(element.cached_path).read_bytes() == b"cached-image-bytes"

            cached_again = await cache.cache_message(cached)
            assert cached_again == cached
            assert http.request_count == 1
        finally:
            await http.close()

    asyncio.run(scenario())


def test_cache_message_keeps_remote_url_when_download_fails(tmp_path: Path) -> None:
    async def scenario() -> None:
        http = await _HttpFixture().start()
        try:
            cache = MediaCache(tmp_path, timeout_seconds=1)
            message = Message(
                chat=FriendChat(uid="u_1", uin=10001),
                sender_uin=10001,
                sender_uid="u_1",
                seq=1,
                timestamp=100,
                elements=[
                    ImageElement(url=f"{http.base_url}/pic.png", md5=b"a", size=18),
                    ImageElement(url=f"{http.base_url}/missing.png", md5=b"b", size=1),
                ],
            )

            cached = await cache.cache_message(message)
            first, second = cached.elements
            assert isinstance(first, ImageElement)
            assert isinstance(second, ImageElement)
            assert first.cached_path
            assert second.cached_path == ""
            assert second.url.endswith("/missing.png")
        finally:
            await http.close()

    asyncio.run(scenario())


def test_cache_message_skips_file_over_size_limit(tmp_path: Path) -> None:
    async def scenario() -> None:
        http = await _HttpFixture().start()
        try:
            cache = MediaCache(tmp_path, max_file_bytes=4)
            message = _image_message(f"{http.base_url}/file.bin")

            cached = await cache.cache_message(message)
            element = cached.elements[0]
            assert isinstance(element, ImageElement)
            assert element.cached_path == ""
            assert not any(path.is_file() for path in tmp_path.rglob("*"))
        finally:
            await http.close()

    asyncio.run(scenario())


def test_cache_message_deduplicates_concurrent_downloads(tmp_path: Path) -> None:
    async def scenario() -> None:
        http = await _HttpFixture().start()
        try:
            cache = MediaCache(tmp_path)
            message = _image_message(f"{http.base_url}/pic.png")

            first, second = await asyncio.gather(cache.cache_message(message), cache.cache_message(message))
            assert first == second
            assert http.request_count == 1
        finally:
            await http.close()

    asyncio.run(scenario())


def test_cache_trim_keeps_total_under_limit(tmp_path: Path) -> None:
    async def scenario() -> None:
        http = await _HttpFixture().start()
        try:
            cache = MediaCache(tmp_path, max_total_bytes=20, max_file_bytes=64)
            messages = [
                _image_message(f"{http.base_url}/pic.png", md5=b"one"),
                _image_message(f"{http.base_url}/pic.png", md5=b"two"),
                _image_message(f"{http.base_url}/pic.png", md5=b"three"),
            ]
            for message in messages:
                await cache.cache_message(message)

            total = sum(path.stat().st_size for path in tmp_path.rglob("*") if path.is_file())
            assert total <= 20
        finally:
            await http.close()

    asyncio.run(scenario())
