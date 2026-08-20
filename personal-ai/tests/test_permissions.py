import asyncio

import pytest

from core.permissions import (
    APPROVAL_WAITERS,
    create_approval,
    resolve_approval,
    wait_for_approval,
)


@pytest.mark.asyncio
async def test_approval_approved_and_cleaned():
    approval_id = create_approval("run-1")
    task = asyncio.create_task(wait_for_approval(approval_id, 1))
    assert resolve_approval(approval_id, True)
    assert await task is True
    assert approval_id not in APPROVAL_WAITERS


@pytest.mark.asyncio
async def test_approval_rejected_and_unknown():
    approval_id = create_approval("run-2")
    task = asyncio.create_task(wait_for_approval(approval_id, 1))
    assert resolve_approval(approval_id, False)
    assert not resolve_approval(approval_id, True)
    assert await task is False
    assert not resolve_approval(approval_id, True)


@pytest.mark.asyncio
async def test_approval_timeout_cleans_waiter():
    approval_id = create_approval("run-3")
    assert await wait_for_approval(approval_id, 0.01) is None
    assert approval_id not in APPROVAL_WAITERS
