"""The backend's connection to the campus-customs MCP server.

Routes read shop facts and perform shop writes only through MCP tools, using the
same server the agents use (mcp_server/server.py over stdio). There is no SQL
in the backend. One connection is opened lazily and kept for the app's
lifetime. The MCP server opens the database fresh on every tool call, so after
a reset the next call already sees the restored file.
"""

import asyncio
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

from pydantic_ai.exceptions import ModelRetry

from agents import build_mcp_toolset


class ShopUnavailable(RuntimeError):
    """The MCP server could not be started or reached."""


class ShopToolError(RuntimeError):
    """An MCP tool refused the request (unknown id, business rule, bad input)."""

    def __init__(self, tool: str, message: str):
        super().__init__(message)
        self.tool = tool
        self.message = message

    @property
    def http_status(self) -> int:
        text = self.message.lower()
        if text.startswith("no ") and "found" in text or "no cash account" in text:
            return 404
        if "approved_by must" in text or "unknown" in text or "must be" in text or "needs sku" in text:
            return 422
        return 409  # business rule: insufficient funds, not open, vendor blocked, amount mismatch...


async def _passthrough(ctx, call_tool, name, args):
    return await call_tool(name, args)


class ShopClient:
    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path
        self._stack: AsyncExitStack | None = None
        self._toolset = None
        self._lock = asyncio.Lock()

    @property
    def connected(self) -> bool:
        return self._toolset is not None

    async def connect(self) -> None:
        async with self._lock:
            if self._toolset is not None:
                return
            stack = AsyncExitStack()
            try:
                toolset = build_mcp_toolset(_passthrough, db_path=self.db_path)
                await stack.enter_async_context(toolset)
            except Exception as exc:
                await stack.aclose()
                raise ShopUnavailable(f"MCP server unavailable: {type(exc).__name__}") from exc
            self._stack, self._toolset = stack, toolset

    async def close(self) -> None:
        async with self._lock:
            if self._stack is not None:
                await self._stack.aclose()
            self._stack, self._toolset = None, None

    async def call(self, tool: str, **args: Any) -> Any:
        if self._toolset is None:
            await self.connect()
        args = {k: v for k, v in args.items() if v is not None}
        try:
            return await self._toolset.direct_call_tool(tool, args)
        except ModelRetry as exc:  # how MCP tool errors surface in pydantic-ai
            raise ShopToolError(tool, str(exc)) from exc
        except Exception as exc:
            # Connection dropped: forget it so the next call reconnects.
            await self.close()
            raise ShopUnavailable(f"MCP call {tool} failed: {type(exc).__name__}") from exc
