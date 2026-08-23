import asyncio

import pytest

from core.chat.run_control import (
    ACTIVE_CHAT_RUNS,
    cancel_chat_run,
    register_chat_run,
    unregister_chat_run,
)


@pytest.mark.asyncio
async def test_registered_chat_run_can_be_explicitly_cancelled():
    ready = asyncio.Event()

    async def worker():
        register_chat_run("a" * 32, "conversation-1")
        ready.set()
        try:
            await asyncio.Event().wait()
        finally:
            unregister_chat_run("a" * 32)

    task = asyncio.create_task(worker())
    await ready.wait()
    assert cancel_chat_run("a" * 32)
    with pytest.raises(asyncio.CancelledError):
        await task
    assert "a" * 32 not in ACTIVE_CHAT_RUNS
    assert not cancel_chat_run("a" * 32)
