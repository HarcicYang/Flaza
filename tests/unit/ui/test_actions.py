"""UiActions 纯函数测试。"""

import asyncio
from pathlib import Path

import httpx

from flaza.ui.actions import _download_to_path, _looks_like_image


def test_looks_like_image_accepts_common_formats() -> None:
    assert _looks_like_image("/tmp/a.png")
    assert _looks_like_image("/tmp/a.JPG")
    assert _looks_like_image("/tmp/a.jpeg")
    assert _looks_like_image("/tmp/a.gif")
    assert _looks_like_image("/tmp/a.webp")
    assert _looks_like_image("/tmp/a.bmp")


def test_looks_like_image_rejects_other_files() -> None:
    assert _looks_like_image("/tmp/a.mp4") is False
    assert _looks_like_image("/tmp/a.txt") is False
    assert _looks_like_image("/tmp/a") is False


def test_download_to_path_streams_http_response(tmp_path: Path) -> None:
    async def scenario() -> None:
        destination = tmp_path / "download" / "saved.txt"
        body = b"hello"

        async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            try:
                await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=5)
            except (TimeoutError, asyncio.IncompleteReadError):
                writer.close()
                return
            header = (
                b"HTTP/1.1 200 OK\r\n"
                b"Content-Type: text/plain\r\n"
                + f"Content-Length: {len(body)}\r\n".encode("ascii")
                + b"Connection: close\r\n\r\n"
            )
            writer.write(header + body)
            await writer.drain()
            writer.close()
            await writer.wait_closed()

        server = await asyncio.start_server(handle, "127.0.0.1", 0)
        port = int(server.sockets[0].getsockname()[1])
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                await _download_to_path(client, f"http://127.0.0.1:{port}/source.txt", str(destination))

            assert destination.read_bytes() == b"hello"
        finally:
            server.close()
            await server.wait_closed()

    asyncio.run(scenario())
