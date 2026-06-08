"""
CRUD endpoints for Meta WhatsApp message templates.

Wraps the Graph API endpoints on the WABA (`WA_BUSINESS_ACCOUNT_ID`) so the
backend can submit, list, inspect, edit, and delete templates without going
through the Meta UI.

Requires `whatsapp_business_management` permission on `WA_ACCESS_TOKEN` —
this is a different scope from the one used for sending messages.

Payloads pass through to Meta verbatim. See Meta's docs for the schema:
https://developers.facebook.com/docs/whatsapp/business-management-api/message-templates
"""

from typing import Annotated, Optional

import requests
from fastapi import APIRouter, Body, HTTPException, Query

from Pipeline.config import (
    WA_ACCESS_TOKEN,
    WA_BUSINESS_ACCOUNT_ID,
    WA_GRAPH_API_VERSION,
)

router = APIRouter()

_BASE_URL = f"https://graph.facebook.com/{WA_GRAPH_API_VERSION}"
_HEADERS = {
    "Authorization": f"Bearer {WA_ACCESS_TOKEN}",
    "Content-Type": "application/json",
}
_TIMEOUT = 10

_TEMPLATE_FIELDS = (
    "id,name,status,language,category,sub_category,components,"
    "quality_score,rejected_reason,message_send_ttl_seconds,"
    "previous_category,correct_category"
)


def _require_waba_id():
    if not WA_BUSINESS_ACCOUNT_ID:
        raise HTTPException(
            status_code=500,
            detail="WA_BUSINESS_ACCOUNT_ID is not set in environment",
        )


def _waba_url() -> str:
    return f"{_BASE_URL}/{WA_BUSINESS_ACCOUNT_ID}/message_templates"


def _template_url(template_id: str) -> str:
    return f"{_BASE_URL}/{template_id}"


def _handle(response: requests.Response):
    try:
        data = response.json()
    except ValueError:
        data = {"raw": response.text}

    if response.status_code >= 400:
        detail = data.get("error", data) if isinstance(data, dict) else data
        raise HTTPException(status_code=response.status_code, detail=detail)
    return data


_WABA_MISSING_RESPONSE = {500: {"description": "`WA_BUSINESS_ACCOUNT_ID` is not configured"}}


@router.post("", summary="Create a new template", responses=_WABA_MISSING_RESPONSE)
def create_template(payload: Annotated[dict, Body()]):
    """
    Submit a new template for Meta review. The payload is forwarded to Meta
    verbatim — provide any fields Meta's create endpoint accepts (`name`,
    `category`, `language`, `components`, etc.).

    Example body:
    ```json
    {
      "name": "reengagement_promo",
      "category": "MARKETING",
      "language": "en",
      "components": [
        {
          "type": "BODY",
          "text": "Hi {{name}}, here is {{offer}} — use {{code}}.",
          "example": {"body_text_named_params": [
            {"param_name": "name",  "example": "Marchel"},
            {"param_name": "offer", "example": "20% off"},
            {"param_name": "code",  "example": "BACK20"}
          ]}
        }
      ]
    }
    ```
    """
    _require_waba_id()
    response = requests.post(_waba_url(), headers=_HEADERS, json=payload, timeout=_TIMEOUT)
    return _handle(response)


@router.get("", summary="List templates on the WABA", responses=_WABA_MISSING_RESPONSE)
def list_templates(
    name: Annotated[Optional[str], Query(description="Filter by exact template name")] = None,
    status: Annotated[Optional[str], Query(description="APPROVED | PENDING | REJECTED | etc.")] = None,
    language: Annotated[Optional[str], Query(description="Language code, e.g. 'en'")] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 25,
):
    _require_waba_id()
    params = {
        "access_token": WA_ACCESS_TOKEN,
        "limit": limit,
        "fields": _TEMPLATE_FIELDS,
    }
    if name:
        params["name"] = name
    if status:
        params["status"] = status
    if language:
        params["language"] = language
    response = requests.get(_waba_url(), params=params, timeout=_TIMEOUT)
    return _handle(response)


@router.get("/{template_id}", summary="Read one template by ID")
def get_template(template_id: str):
    response = requests.get(
        _template_url(template_id),
        params={"access_token": WA_ACCESS_TOKEN, "fields": _TEMPLATE_FIELDS},
        timeout=_TIMEOUT,
    )
    return _handle(response)


@router.post("/{template_id}", summary="Update an existing template")
def update_template(template_id: str, payload: Annotated[dict, Body()]):
    """
    Edit an existing template. Meta uses POST for updates (not PATCH/PUT).

    Editable: `components`, `category` (limited cases). Immutable: `name`,
    `language`. An edit re-triggers Meta's review process.
    """
    response = requests.post(
        _template_url(template_id), headers=_HEADERS, json=payload, timeout=_TIMEOUT
    )
    return _handle(response)


@router.delete(
    "/{template_id}",
    summary="Delete a template by ID",
    responses={
        **_WABA_MISSING_RESPONSE,
        404: {"description": "Template ID does not resolve to a known template name"},
    },
)
def delete_template(template_id: str):
    """
    Delete a specific template (one language version) by ID.

    Meta's delete endpoint requires both `hsm_id` and `name` together, so the
    route first fetches the template to read its `name`, then issues the delete.
    """
    _require_waba_id()

    lookup = requests.get(
        _template_url(template_id),
        params={"access_token": WA_ACCESS_TOKEN, "fields": "name"},
        timeout=_TIMEOUT,
    )
    template = _handle(lookup)
    name = template.get("name")
    if not name:
        raise HTTPException(
            status_code=404,
            detail=f"Could not resolve template name for ID {template_id}",
        )

    response = requests.delete(
        _waba_url(),
        params={"access_token": WA_ACCESS_TOKEN, "hsm_id": template_id, "name": name},
        timeout=_TIMEOUT,
    )
    return _handle(response)
