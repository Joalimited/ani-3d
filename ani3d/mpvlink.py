"""One interface to mpv's JSON IPC: a Unix socket on Linux/macOS, an overlapped named pipe on Windows."""
import asyncio
import json
import sys


class UnixLink:
    def __init__(self, reader, writer):
        self.reader, self.writer = reader, writer

    async def readline(self):
        return await self.reader.readline()

    async def send(self, cmd):
        self.writer.write((json.dumps({"command": list(cmd)}) + "\n").encode())
        await self.writer.drain()

    def close(self):
        try:
            self.writer.close()
        except Exception:  # noqa: BLE001
            pass


async def connect(path, proc, tries=100):
    """Wait for mpv to create its IPC endpoint and connect. Returns a link, or None if mpv exited first."""
    loop = asyncio.get_running_loop()
    for _ in range(tries):
        try:
            if sys.platform == "win32":
                # overlapped I/O through the Proactor loop: a plain blocking handle would let a pending read block every write
                reader = asyncio.StreamReader()
                protocol = asyncio.StreamReaderProtocol(reader)
                transport, _ = await loop.create_pipe_connection(lambda: protocol, path)
                return UnixLink(reader, asyncio.StreamWriter(transport, protocol, reader, loop))
            reader, writer = await asyncio.open_unix_connection(path)
            return UnixLink(reader, writer)
        except (OSError, ConnectionError):
            if proc.returncode is not None:
                return None
            await asyncio.sleep(0.1)
    return None
