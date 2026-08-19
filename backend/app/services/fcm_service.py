import asyncio
from functools import lru_cache

import firebase_admin
from firebase_admin import credentials, exceptions, messaging

from app.config import settings
from app.core.logging import logger


@lru_cache(maxsize=1)
def _get_app() -> firebase_admin.App | None:
    """Firebase 서비스 계정 키가 설정된 경우에만 앱을 초기화한다.

    미설정 시 None을 반환하여 푸시 발송을 조용히 건너뛴다 —
    Firebase 프로젝트 없이도 나머지 기능은 정상 동작해야 한다.
    """
    if not settings.FIREBASE_CREDENTIALS_JSON:
        return None
    try:
        cred = credentials.Certificate(settings.FIREBASE_CREDENTIALS_JSON)
        return firebase_admin.initialize_app(cred)
    except Exception:
        logger.exception("Firebase 초기화 실패 — FIREBASE_CREDENTIALS_JSON 경로를 확인하세요.")
        return None


def is_configured() -> bool:
    return _get_app() is not None


async def send_push(token: str, title: str, body: str, data: dict[str, str] | None = None) -> bool | None:
    """단일 기기로 푸시 알림을 발송한다.

    반환값이 세 갈래다 — True면 발송 성공, False면 토큰이 만료된 거라 호출자가
    fcm_token을 지워야 하고, None이면 미설정이거나 일시적 오류라 토큰은 그대로 둔다.
    """
    app = _get_app()
    if app is None:
        return None

    message = messaging.Message(
        token=token,
        notification=messaging.Notification(title=title, body=body),
        data=data or {},
    )

    try:
        await asyncio.to_thread(messaging.send, message, app=app)
        return True
    except exceptions.NotFoundError:
        logger.info("FCM 토큰이 더 이상 유효하지 않습니다 (미등록).")
        return False
    except exceptions.FirebaseError:
        logger.exception("FCM 푸시 발송 실패 (일시적 오류로 간주, 토큰 유지)")
        return None
