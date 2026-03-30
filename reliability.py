import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional


@dataclass
class CircuitState:
    failures: int = 0
    open_until: float = 0.0


class ResilienceError(Exception):
    def __init__(self, operation: str, failure_class: str, original: Exception):
        self.operation = operation
        self.failure_class = failure_class
        self.original = original
        super().__init__(f"{operation} failed ({failure_class}): {original}")


_LOCK = threading.Lock()
_CIRCUITS: Dict[str, CircuitState] = {}


def classify_failure(exc: Exception) -> str:
    name = type(exc).__name__.lower()
    text = str(exc).lower()
    if "auth" in name or "unauthorized" in text or "forbidden" in text or "401" in text or "403" in text:
        return "auth"
    if "rate" in text or "429" in text:
        return "rate_limit"
    if "timeout" in name or "timed out" in text:
        return "timeout"
    if any(token in text for token in ("overloaded", "service unavailable", "503", "529", "network", "connection")):
        return "offline"
    return "unknown"


def _breaker_allows_call(key: str) -> bool:
    now = time.time()
    with _LOCK:
        state = _CIRCUITS.setdefault(key, CircuitState())
        return state.open_until <= now


def _breaker_record_success(key: str) -> None:
    with _LOCK:
        state = _CIRCUITS.setdefault(key, CircuitState())
        state.failures = 0
        state.open_until = 0.0


def _breaker_record_failure(key: str, threshold: int, open_seconds: int) -> None:
    now = time.time()
    with _LOCK:
        state = _CIRCUITS.setdefault(key, CircuitState())
        state.failures += 1
        if state.failures >= threshold:
            state.open_until = now + open_seconds


def _call_with_timeout(fn: Callable[[], Any], timeout_s: Optional[float]) -> Any:
    if not timeout_s or timeout_s <= 0:
        return fn()
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(fn)
        try:
            return future.result(timeout=timeout_s)
        except FuturesTimeoutError as exc:
            raise TimeoutError(f"Timed out after {timeout_s:.1f}s") from exc


def run_with_resilience(
    fn: Callable[[], Any],
    operation: str,
    retries: int = 3,
    timeout_s: Optional[float] = None,
    base_delay_s: float = 0.6,
    breaker_key: Optional[str] = None,
    breaker_threshold: int = 3,
    breaker_open_seconds: int = 30,
) -> Any:
    key = breaker_key or operation
    if not _breaker_allows_call(key):
        raise ResilienceError(operation, "offline", RuntimeError("Circuit breaker is open"))

    last_exc: Optional[Exception] = None
    for attempt in range(1, retries + 1):
        try:
            result = _call_with_timeout(fn, timeout_s)
            _breaker_record_success(key)
            return result
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            _breaker_record_failure(key, breaker_threshold, breaker_open_seconds)
            if attempt == retries:
                failure_class = classify_failure(exc)
                raise ResilienceError(operation, failure_class, exc) from exc
            delay = base_delay_s * (2 ** (attempt - 1)) + random.uniform(0, 0.3)
            time.sleep(delay)

    # defensive fallback
    raise ResilienceError(operation, "unknown", last_exc or RuntimeError("Unknown failure"))
