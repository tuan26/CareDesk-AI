import time
from collections import defaultdict, deque
from fastapi import HTTPException, Request, status
from backend.app.core.config import settings


class RateLimiter:
    """
    Simple in-memory sliding-window rate limiter per client IP.
    Suitable for a single-process deployment; swap for Redis-based limiting when scaling out.
    """

    def __init__(self, times: int = None, seconds: int = 60, scope: str = "default"):
        self.times = times or settings.RATE_LIMIT_PER_MINUTE
        self.seconds = seconds
        self.scope = scope
        self._hits: dict[str, deque] = defaultdict(deque)

    def __call__(self, request: Request):
        client_ip = request.client.host if request.client else "unknown"
        key = f"{self.scope}:{client_ip}"
        now = time.monotonic()
        window = self._hits[key]

        while window and now - window[0] > self.seconds:
            window.popleft()

        if len(window) >= self.times:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Bạn thao tác quá nhanh. Vui lòng thử lại sau ít phút."
            )
        window.append(now)


# Shared limiter instances
chat_rate_limiter = RateLimiter(scope="chat")
public_rate_limiter = RateLimiter(times=10, scope="public")
register_rate_limiter = RateLimiter(times=5, seconds=300, scope="register")
