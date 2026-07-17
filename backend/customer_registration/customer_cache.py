"""Redis tag helpers for customer reads.

These live outside customer.py so that other routers can invalidate customer
caches without importing it. The import would be circular: customer.py pulls in
backend.customer_service.bulk_lead_assignment, which runs the customer_service
package __init__ -> customer_service.py. If customer_service.py then imported
customer.py at module level it would get a half-initialised module whose helpers
are not defined yet, and fail at import time rather than at runtime.
"""

from backend.payments.payment_cache_invalidation import invalidate_followup_caches
from backend.redis_cache import invalidate_tag as redis_invalidate_tag


def customer_get_by_id_tag(customer_id: int) -> str:
    return f"customer:get_by_id:index:{customer_id}"


def customer_filter_tag() -> str:
    return "customer:filter:index"


async def invalidate_customer_cache(customer_id: int) -> None:
    # Customer detail + list caches. If GST (or other) GET endpoints add Redis later,
    # invalidate their tags here too when customer fields affect those responses.
    await redis_invalidate_tag(customer_get_by_id_tag(customer_id))
    await redis_invalidate_tag(customer_filter_tag())
    await invalidate_followup_caches()
