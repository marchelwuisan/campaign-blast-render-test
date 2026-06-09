from typing import Annotated, Optional

from fastapi import APIRouter, Body, HTTPException, Query

from Pipeline.messaging import template_service, template_store

router = APIRouter()

_WABA_MISSING_RESPONSE = {500: {"description": "`WA_BUSINESS_ACCOUNT_ID` is not configured"}}


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except template_service.TemplateApiError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)


@router.post("/sync", summary="Sync the local template db from Meta",
             responses=_WABA_MISSING_RESPONSE)
def sync_templates():
    count = _call(template_service.sync_all)
    return {"synced": count}


@router.post("", summary="Create a new template", responses=_WABA_MISSING_RESPONSE)
def create_template(payload: Annotated[dict, Body()]):
    result = _call(template_service.create_remote, payload)
    template_service.sync_quietly()
    return result


@router.get("", summary="List templates", responses=_WABA_MISSING_RESPONSE)
def list_templates(
    name: Annotated[Optional[str], Query(description="Filter by exact template name")] = None,
    status: Annotated[Optional[str], Query(description="APPROVED | PENDING | REJECTED | etc.")] = None,
    language: Annotated[Optional[str], Query(description="Language code, e.g. 'en'")] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 25,
):
    # Cold start: if nothing is cached yet, pull from Meta once.
    if template_store.count_local() == 0:
        template_service.sync_quietly()
    return {"data": template_store.list_local(name, status, language, limit)}


@router.get("/{template_id}", summary="Read one template")
def get_template(template_id: str):
    template = template_store.get_local(template_id)
    if template is None:
        # Not cached — fall back to Meta and refresh the cache for next time.
        template = _call(template_service.get_remote, template_id)
        template_service.sync_quietly()
    return template


@router.post("/{template_id}", summary="Update an existing template")
def update_template(template_id: str, payload: Annotated[dict, Body()]):
    result = _call(template_service.update_remote, template_id, payload)
    template_service.sync_quietly()
    return result


@router.delete(
    "/{template_id}",
    summary="Delete a template by ID",
    responses={
        **_WABA_MISSING_RESPONSE,
        404: {"description": "Template ID does not resolve to a known template name"},
    },
)
def delete_template(template_id: str):
    result = _call(template_service.delete_remote, template_id)
    template_service.sync_quietly()
    return result
