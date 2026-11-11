"""连接已有 SSH Codex daemon，不启动模型服务或创建会话。"""

from pathlib import Path

from websockets.asyncio.client import ClientConnection, unix_connect
from websockets.exceptions import ConnectionClosed, ConnectionClosedOK

from .protocol import JsonRpcConnection


class DaemonConnection(JsonRpcConnection):
    def __init__(self, connection: ClientConnection) -> None:
        self._connection = connection
        super().__init__()

    @classmethod
    async def connect(cls, socket: Path) -> "DaemonConnection":
        return cls(await unix_connect(str(socket)))

    async def _write(self, message: str) -> None:
        try:
            await self._connection.send(message)
        except ConnectionClosed as error:
            raise OSError("Codex daemon 连接已关闭。") from error

    async def _receive(self) -> str | bytes | None:
        try:
            return await self._connection.recv()
        except ConnectionClosedOK:
            return None
        except ConnectionClosed as error:
            raise OSError("Codex daemon 连接中断。") from error

    async def close(self) -> None:
        self._closing = True
        await self._connection.close()
        await self._reader
