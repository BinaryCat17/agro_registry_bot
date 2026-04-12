import os
import requests
from dotenv import load_dotenv

_ENV_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
if os.path.exists(_ENV_PATH):
    load_dotenv(_ENV_PATH)

CLIENT_ID = os.getenv("YANDEX_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("YANDEX_CLIENT_SECRET", "")
PUBLIC_HOST = os.getenv("PUBLIC_HOST", "https://agrochem.salskayastep.ru")
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "vv.smirnov17@ya.ru")
REDIRECT_URI = f"{PUBLIC_HOST.rstrip('/')}/auth/callback/yandex"


def get_auth_url(state: str = ""):
    if not CLIENT_ID:
        raise RuntimeError("YANDEX_CLIENT_ID не настроен")
    return (
        f"https://oauth.yandex.ru/authorize?"
        f"response_type=code&"
        f"client_id={CLIENT_ID}&"
        f"redirect_uri={REDIRECT_URI}&"
        f"state={state}"
    )


def exchange_code(code: str):
    if not CLIENT_ID or not CLIENT_SECRET:
        raise RuntimeError("YANDEX_CLIENT_ID или YANDEX_CLIENT_SECRET не настроены")
    resp = requests.post(
        "https://oauth.yandex.ru/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "redirect_uri": REDIRECT_URI,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    resp.raise_for_status()
    return resp.json()


def get_user_info(access_token: str):
    resp = requests.get(
        "https://login.yandex.ru/info",
        headers={"Authorization": f"OAuth {access_token}"},
        params={"format": "json"},
    )
    resp.raise_for_status()
    return resp.json()
