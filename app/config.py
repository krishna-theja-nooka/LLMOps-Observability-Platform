import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    db_path: str = "data/gateway.sqlite3"
    api_key: str = ""
    allow_simulation: bool = True
    timeout_s: float = 0.1
    retries: int = 2
    backoff_s: float = 0.01
    circuit_threshold: int = 3
    circuit_reset_s: float = 5.0
    rate_limit: int = 30
    rate_window_s: float = 60.0
    cache_ttl_s: float = 60.0
    cache_capacity: int = 512
    client_capacity: int = 1024

    def __post_init__(self):
        for name in (
            "timeout_s",
            "circuit_threshold",
            "circuit_reset_s",
            "rate_limit",
            "rate_window_s",
            "cache_ttl_s",
            "cache_capacity",
            "client_capacity",
        ):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")
        if self.retries < 0 or self.backoff_s < 0:
            raise ValueError("retries and backoff_s must be nonnegative")

    @classmethod
    def from_env(cls):
        return cls(
            db_path=os.getenv("GATEWAY_DB_PATH", "data/gateway.sqlite3"),
            api_key=os.getenv("GATEWAY_API_KEY", ""),
            allow_simulation=os.getenv("GATEWAY_ALLOW_SIMULATION", "true").lower() == "true",
        )
