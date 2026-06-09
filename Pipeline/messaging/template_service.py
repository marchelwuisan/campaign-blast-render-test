import requests

from Pipeline.config import (
    WA_ACCESS_TOKEN,
    WA_APP_ID,
    WA_BUSINESS_ACCOUNT_ID,
    WA_GRAPH_API_VERSION,
)
from Pipeline.messaging import template_store

_BASE_URL = f"https://graph.facebook.com/{WA_GRAPH_API_VERSION}"
_HEADERS = {
    "Authorization": f"Bearer {WA_ACCESS_TOKEN}",
    "Content-Type": "application/json",
}
_TIMEOUT = 10

# Fields requested from Meta when listing/reading templates.
_TEMPLATE_FIELDS = (
    "id,name,status,language,category,sub_category,components,"
    "quality_score,rejected_reason,message_send_ttl_seconds,"
    "previous_category,correct_category,parameter_format"
)


class TemplateApiError(Exception):

    def __init__(self, status_code: int, detail):
        super().__init__(str(detail))
        self.status_code = status_code
        self.detail = detail


def _require_waba_id() -> None:
    if not WA_BUSINESS_ACCOUNT_ID:
        raise TemplateApiError(500, "WA_BUSINESS_ACCOUNT_ID is not set in environment")


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
        raise TemplateApiError(response.status_code, detail)
    return data


def fetch_all_from_meta() -> list[dict]:
    _require_waba_id()
    templates: list[dict] = []
    url = _waba_url()
    params = {
        "access_token": WA_ACCESS_TOKEN,
        "fields": _TEMPLATE_FIELDS,
        "limit": 100,
    }
    while url:
        data = _handle(requests.get(url, params=params, timeout=_TIMEOUT))
        templates.extend(data.get("data", []))
        # `paging.next` is a fully-formed URL with its own querystring.
        url = data.get("paging", {}).get("next")
        params = None
    return templates


def get_remote(template_id: str) -> dict:
    return _handle(
        requests.get(
            _template_url(template_id),
            params={"access_token": WA_ACCESS_TOKEN, "fields": _TEMPLATE_FIELDS},
            timeout=_TIMEOUT,
        )
    )

def create_remote(payload: dict) -> dict:
    _require_waba_id()
    return _handle(
        requests.post(_waba_url(), headers=_HEADERS, json=payload, timeout=_TIMEOUT)
    )


def update_remote(template_id: str, payload: dict) -> dict:
    return _handle(
        requests.post(
            _template_url(template_id), headers=_HEADERS, json=payload, timeout=_TIMEOUT
        )
    )


def upload_media_handle(file_bytes: bytes, file_name: str, file_type: str) -> str:
    if not WA_APP_ID:
        raise TemplateApiError(500, "WA_APP_ID is not set in environment")

    session = _handle(
        requests.post(
            f"{_BASE_URL}/{WA_APP_ID}/uploads",
            params={
                "access_token": WA_ACCESS_TOKEN,
                "file_name": file_name,
                "file_length": len(file_bytes),
                "file_type": file_type,
            },
            timeout=_TIMEOUT,
        )
    )
    session_id = session.get("id")
    if not session_id:
        raise TemplateApiError(502, "Meta did not return an upload session id")

    result = _handle(
        requests.post(
            f"{_BASE_URL}/{session_id}",
            headers={"Authorization": f"OAuth {WA_ACCESS_TOKEN}", "file_offset": "0"},
            data=file_bytes,
            timeout=30,
        )
    )
    handle = result.get("h")
    if not handle:
        raise TemplateApiError(502, "Meta did not return a media handle")
    return handle


def delete_remote(template_id: str) -> dict:
    _require_waba_id()
    template = _handle(
        requests.get(
            _template_url(template_id),
            params={"access_token": WA_ACCESS_TOKEN, "fields": "name"},
            timeout=_TIMEOUT,
        )
    )
    name = template.get("name")
    if not name:
        raise TemplateApiError(
            404, f"Could not resolve template name for ID {template_id}"
        )
    return _handle(
        requests.delete(
            _waba_url(),
            params={"access_token": WA_ACCESS_TOKEN, "hsm_id": template_id, "name": name},
            timeout=_TIMEOUT,
        )
    )

def sync_all() -> int:
    return template_store.replace_all(fetch_all_from_meta())


def sync_quietly() -> int | None:
    try:
        return sync_all()
    except Exception as exc:  # noqa: BLE001
        print(f"[template_service] cache sync failed: {exc}")
        return None


def validate_sendable(specs: set[tuple[str, str]]) -> dict[str, str]:
    errors: dict[str, str] = {}
    for name, language in specs:
        key = f"{name} ({language})"
        matches = template_store.list_local(name=name, language=language, limit=1)
        if not matches:
            errors[key] = "template not found on WABA"
        elif matches[0].get("status") != "APPROVED":
            errors[key] = f"template not approved (status: {matches[0].get('status')})"
    return errors
