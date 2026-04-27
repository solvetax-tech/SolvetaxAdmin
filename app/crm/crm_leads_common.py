from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile

from app.crm.crm_leads import (
    bulk_import_crm_leads_file as _bulk_import_crm_leads_file,
    execute_bulk_assign as _execute_bulk_assign,
    filter_crm_activities as _filter_crm_activities,
    filter_crm_leads as _filter_crm_leads,
    get_bulk_assign_candidates as _get_bulk_assign_candidates,
    get_crm_lead_by_entity as _get_crm_lead_by_entity,
    get_crm_lead_stages as _get_crm_lead_stages,
    get_crm_stage_pitch_mappings as _get_crm_stage_pitch_mappings,
    list_crm_activities as _list_crm_activities,
    list_crm_lead_call_activities as _list_crm_lead_call_activities,
    list_crm_lead_stage_activity_history as _list_crm_lead_stage_activity_history,
)
from app.crm.schemas import CRMBulkAssignExecuteIn
from app.security.rbac import require_permission

router = APIRouter(prefix="/api/v1/crm/leads", tags=["CRM Leads Common"])


@router.get("/ui-mappings", summary="CRM stage/pitch and pitch/status mappings for UI")
async def get_crm_stage_pitch_mappings(
    entity_type: str = Query(...),
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    return await _get_crm_stage_pitch_mappings(entity_type=entity_type, current_user=current_user)


@router.get("/filter", summary="Filter CRM leads")
async def filter_crm_leads(
    stage: Optional[str] = None,
    stages: Optional[List[str]] = Query(None, description="Filter by multiple stages (OR logic)."),
    follow_up_status: Optional[str] = None,
    mobile: Optional[str] = None,
    rm_id: Optional[int] = None,
    op_id: Optional[int] = None,
    lead_type: Optional[str] = None,
    tag: Optional[str] = None,
    lead_source: Optional[str] = None,
    is_active: Optional[bool] = None,
    entity_type: str = Query(...),
    entity_id: Optional[int] = Query(None, ge=1),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    return await _filter_crm_leads(
        stage=stage,
        stages=stages,
        follow_up_status=follow_up_status,
        mobile=mobile,
        rm_id=rm_id,
        op_id=op_id,
        lead_type=lead_type,
        tag=tag,
        lead_source=lead_source,
        is_active=is_active,
        entity_type=entity_type,
        entity_id=entity_id,
        limit=limit,
        offset=offset,
        current_user=current_user,
    )


@router.post("/bulk-import/file", summary="Bulk import CRM leads by CSV/XLSX upload")
async def bulk_import_crm_leads_file(
    file: UploadFile = File(...),
    update_if_exists: bool = Form(True),
    validate_only: bool = Form(False),
    current_user=Depends(require_permission("EMPLOYEE", "DELETE")),
):
    return await _bulk_import_crm_leads_file(
        file=file,
        update_if_exists=update_if_exists,
        validate_only=validate_only,
        current_user=current_user,
    )


@router.get("/bulk-assign/candidates", summary="Get lead candidates for bulk assignment")
async def get_bulk_assign_candidates(
    stages: Optional[List[str]] = Query(None),
    rm_ids: Optional[List[int]] = Query(None),
    op_ids: Optional[List[int]] = Query(None),
    lead_types: Optional[List[str]] = Query(None),
    tags: Optional[List[str]] = Query(None),
    lead_sources: Optional[List[str]] = Query(None),
    entity_types: List[str] = Query(...),
    follow_up_statuses: Optional[List[str]] = Query(None),
    null_fields: Optional[List[str]] = Query(None),
    not_null_fields: Optional[List[str]] = Query(None),
    is_active: Optional[bool] = None,
    match_mode: str = Query("AND", description="AND or OR across provided filters."),
    filter_mode: str = Query("IN", description="IN or NOT_IN for provided filter values."),
    limit: int = Query(500, ge=1, le=5000),
    offset: int = Query(0, ge=0),
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    return await _get_bulk_assign_candidates(
        stages=stages,
        rm_ids=rm_ids,
        op_ids=op_ids,
        lead_types=lead_types,
        tags=tags,
        lead_sources=lead_sources,
        entity_types=entity_types,
        follow_up_statuses=follow_up_statuses,
        null_fields=null_fields,
        not_null_fields=not_null_fields,
        is_active=is_active,
        match_mode=match_mode,
        filter_mode=filter_mode,
        limit=limit,
        offset=offset,
        current_user=current_user,
    )


@router.post("/bulk-assign/execute", summary="Assign selected leads to employees in round robin")
async def execute_bulk_assign(
    payload: CRMBulkAssignExecuteIn,
    current_user=Depends(require_permission("EMPLOYEE", "DELETE")),
):
    return await _execute_bulk_assign(payload=payload, current_user=current_user)


@router.get("/activities/filter", summary="Filter CRM activities (visible leads only)")
async def filter_crm_activities(
    lead_id: Optional[int] = Query(None, ge=1),
    activity_type: Optional[str] = None,
    call_type_code: Optional[str] = None,
    call_status_code: Optional[str] = None,
    old_stage: Optional[str] = None,
    new_stage: Optional[str] = None,
    performed_by: Optional[int] = Query(None, gt=0),
    performed_at_from: Optional[datetime] = None,
    performed_at_to: Optional[datetime] = None,
    mobile: Optional[str] = None,
    lead_stage: Optional[str] = None,
    lead_is_active: Optional[bool] = None,
    entity_type: str = Query(...),
    entity_id: Optional[int] = Query(None, ge=1),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    return await _filter_crm_activities(
        lead_id=lead_id,
        activity_type=activity_type,
        call_type_code=call_type_code,
        call_status_code=call_status_code,
        old_stage=old_stage,
        new_stage=new_stage,
        performed_by=performed_by,
        performed_at_from=performed_at_from,
        performed_at_to=performed_at_to,
        mobile=mobile,
        lead_stage=lead_stage,
        lead_is_active=lead_is_active,
        entity_type=entity_type,
        entity_id=entity_id,
        limit=limit,
        offset=offset,
        current_user=current_user,
    )


@router.get("/stages", summary="CRM lead pipeline stages for UI")
async def get_crm_lead_stages(
    entity_type: str = Query(...),
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    return await _get_crm_lead_stages(entity_type=entity_type, current_user=current_user)


@router.get("/by-entity", summary="Get CRM lead by entity_type + entity_id (visible to caller)")
async def get_crm_lead_by_entity(
    entity_id: int = Query(..., ge=1),
    entity_type: str = Query(...),
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    return await _get_crm_lead_by_entity(
        entity_id=entity_id,
        entity_type=entity_type,
        current_user=current_user,
    )


@router.get(
    "/{lead_id:int}/activities/calls",
    summary="Call log for a lead (dial/connect timestamps + outcome + stage at time of call)",
)
async def list_crm_lead_call_activities(
    lead_id: int,
    entity_type: str = Query(...),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    return await _list_crm_lead_call_activities(
        lead_id=lead_id,
        entity_type=entity_type,
        limit=limit,
        offset=offset,
        current_user=current_user,
    )


@router.get(
    "/{lead_id:int}/activities/stage-history",
    summary="Stage change timeline for a lead (from activities)",
)
async def list_crm_lead_stage_activity_history(
    lead_id: int,
    entity_type: str = Query(...),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    return await _list_crm_lead_stage_activity_history(
        lead_id=lead_id,
        entity_type=entity_type,
        limit=limit,
        offset=offset,
        current_user=current_user,
    )


@router.get("/{lead_id:int}/activities", summary="Get CRM lead activities")
async def list_crm_activities(
    lead_id: int,
    entity_type: str = Query(...),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    return await _list_crm_activities(
        lead_id=lead_id,
        entity_type=entity_type,
        limit=limit,
        offset=offset,
        current_user=current_user,
    )
