from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal


@dataclass
class VerifyResult:
    status: Literal["valid", "catch_all", "invalid", "unknown"]
    confidence: float = 0.0
    raw: dict | None = None


class EmailVerifier(ABC):
    @abstractmethod
    def verify(self, email: str) -> VerifyResult: ...
