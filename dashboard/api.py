import requests

BASE_URL = "http://127.0.0.1:8000"


def get(path: str, params: dict = None):
    r = requests.get(f"{BASE_URL}{path}", params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def post(path: str, body: dict = None):
    r = requests.post(f"{BASE_URL}{path}", json=body or {}, timeout=30)
    r.raise_for_status()
    return r.json()
