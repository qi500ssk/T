"""单进程审批等待器；P3 不持久化待审批状态。"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass


@dataclass
class ApprovalWaiter:
    run_id: str
    event: asyncio.Event
    approved: bool | None = None


APPROVAL_WAITERS: dict[str, ApprovalWaiter] = {}


def create_approval(run_id: str) -> str:
    approval_id = uuid.uuid4().hex
    APPROVAL_WAITERS[approval_id] = ApprovalWaiter(run_id=run_id, event=asyncio.Event())
    return approval_id


def resolve_approval(approval_id: str, approved: bool) -> bool:
    waiter = APPROVAL_WAITERS.get(approval_id)
    if waiter is None or waiter.approved is not None:
        return False
    waiter.approved = approved
    waiter.event.set()
    return True


async def wait_for_approval(approval_id: str, timeout: float) -> bool | None:
    waiter = APPROVAL_WAITERS.get(approval_id)
    if waiter is None:
        return None
    try:
        await asyncio.wait_for(waiter.event.wait(), timeout=timeout)
        return waiter.approved
    except TimeoutError:
        return None
    finally:
        APPROVAL_WAITERS.pop(approval_id, None)


def cancel_run_approvals(run_id: str) -> None:
    for approval_id, waiter in list(APPROVAL_WAITERS.items()):
        if waiter.run_id == run_id and waiter.approved is None:
            waiter.approved = False
            waiter.event.set()
            APPROVAL_WAITERS.pop(approval_id, None)


def reject_all_approvals() -> None:
    for approval_id, waiter in list(APPROVAL_WAITERS.items()):
        if waiter.approved is None:
            waiter.approved = False
            waiter.event.set()
            APPROVAL_WAITERS.pop(approval_id, None)
