"""Shared Redis tag invalidation after payment ledger writes."""

from typing import Optional

from app.Dashboard.service_done_payment_pending import invalidate_service_done_payment_pending_cache
from app.redis_cache import invalidate_tag as redis_invalidate_tag

_REGISTRATION_PAYMENTS_FILTER_TAG = "registration_payments:filter:index"
_PAYMENTS_CONFIG_AMOUNT_TAG = "payments_config:get_amount:index"

_PAYMENT_FOLLOWUP_TAGS = (
    "payment_followups:list:index",
    "payment_followups:counts:index",
    "payment_followups:alerts:index",
)

_GST_FILING_TABLE_TAGS = (
    "gst_filing:table:filings:index",
    "gst_filing:table:return_details:index",
)

_CUSTOMER_SERVICE_TAGS = (
    "customer_services:filter:index",
    "customer_services:dashboard:index",
    "customer_services:pending:index",
    "customer_services:progress_tracker:index",
)

_CUSTOMER_SERVICE_FOLLOWUP_TAGS = (
    "customer_service_followups:list:index",
    "customer_service_followups:counts:index",
    "customer_service_followups:alerts:index",
)

_CRM_TAGS = (
    "crm:leads:filter:index",
    "crm:activities:filter:index",
    "crm:lead:by_entity:index",
)


async def _invalidate_tags(tags: tuple[str, ...]) -> None:
    for tag in tags:
        await redis_invalidate_tag(tag)


async def invalidate_followup_caches() -> None:
    """Invalidate service + payment follow-up list/counts/alerts caches."""
    await _invalidate_tags(_PAYMENT_FOLLOWUP_TAGS)
    await _invalidate_tags(_CUSTOMER_SERVICE_FOLLOWUP_TAGS)


async def invalidate_payment_followup_caches() -> None:
    """Backward-compatible alias."""
    await invalidate_followup_caches()


async def invalidate_payment_related_caches(
    *,
    gst_registration_id: Optional[int] = None,
    income_tax_id: Optional[int] = None,
    gst_filing: bool = False,
    customer_service: bool = False,
    crm: bool = False,
) -> None:
    """Invalidate caches commonly stale after any payment write."""
    await redis_invalidate_tag(_REGISTRATION_PAYMENTS_FILTER_TAG)
    await redis_invalidate_tag(_PAYMENTS_CONFIG_AMOUNT_TAG)
    await invalidate_service_done_payment_pending_cache()
    await _invalidate_tags(_PAYMENT_FOLLOWUP_TAGS)

    if gst_filing:
        await _invalidate_tags(_GST_FILING_TABLE_TAGS)

    if customer_service:
        await _invalidate_tags(_CUSTOMER_SERVICE_TAGS)
        await _invalidate_tags(_CUSTOMER_SERVICE_FOLLOWUP_TAGS)

    if gst_registration_id is not None:
        await redis_invalidate_tag("gst_registration:filter:index")
        await redis_invalidate_tag(f"gst_registration:detail:index:{gst_registration_id}")

    if income_tax_id is not None:
        await redis_invalidate_tag("income_tax:filter:index")
        await redis_invalidate_tag(f"income_tax:detail:index:{income_tax_id}")

    if crm:
        await _invalidate_tags(_CRM_TAGS)
