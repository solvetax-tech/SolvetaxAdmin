"""Redis cache invalidation for employee create/edit flows."""

from typing import Optional

from backend.redis_cache import invalidate_tag as redis_invalidate_tag


def employee_filter_tag() -> str:
    return "employee:filter:index"


def employee_by_id_tag(emp_id: int) -> str:
    return f"employee:get_by_id:index:{emp_id}"


def employee_active_rm_tag() -> str:
    return "employee:active_rm:index"


def employee_active_op_tag() -> str:
    return "employee:active_op:index"


def employee_active_managers_tag() -> str:
    return "employee:active_managers:index"


def roles_list_tag() -> str:
    return "employee:roles:list:index"


async def invalidate_employee_related_cache(emp_id: Optional[int] = None) -> None:
    """Clear employee list/detail/active-RM/OP caches after create or edit."""
    from backend.payments.payment_cache_invalidation import invalidate_followup_caches

    await redis_invalidate_tag(employee_filter_tag())
    await redis_invalidate_tag(employee_active_rm_tag())
    await redis_invalidate_tag(employee_active_op_tag())
    await redis_invalidate_tag(employee_active_managers_tag())
    await redis_invalidate_tag(roles_list_tag())
    await redis_invalidate_tag("version:filter:index")
    await invalidate_followup_caches()
    if emp_id is not None:
        await redis_invalidate_tag(employee_by_id_tag(emp_id))
