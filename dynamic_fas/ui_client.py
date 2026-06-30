from typing import Any, Dict

import requests


class DynamicFasApiError(RuntimeError):
    """A user-facing error returned by the Dynamic FAS API client."""


def _post_json(
    api_base: str,
    path: str,
    payload: Dict[str, Any],
    *,
    timeout: int = 60,
) -> Dict[str, Any]:
    url = f"{api_base.rstrip('/')}{path}"

    try:
        response = requests.post(url, json=payload, timeout=timeout)
    except requests.RequestException as exc:
        raise DynamicFasApiError(f"Could not connect to {url}: {exc}") from exc

    if not response.ok:
        message = f"The API returned error {response.status_code}"
        try:
            body = response.json()
            if isinstance(body, dict):
                detail = body.get("detail")
                if isinstance(detail, str):
                    message = detail
        except ValueError:
            pass
        raise DynamicFasApiError(message)

    try:
        body = response.json()
    except ValueError as exc:
        raise DynamicFasApiError("The API returned an invalid JSON response") from exc

    if not isinstance(body, dict):
        raise DynamicFasApiError("The API returned an unexpected response")
    return body


def chat_with_dynamic_fas(
    api_base: str,
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    return _post_json(api_base, "/dynamic-fas/chat", payload)


def reset_dynamic_fas_session(
    api_base: str,
    session_id: str,
) -> Dict[str, Any]:
    return _post_json(
        api_base,
        "/dynamic-fas/reset-session",
        {"session_id": session_id},
    )
