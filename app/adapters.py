import asyncio
import math
from dataclasses import dataclass
from typing import Protocol

from app.models import Scenario


class ProviderFailure(Exception):
    """Retryable provider failure; deliberately contains no prompt text."""


class OutputBlocked(Exception):
    """The demonstration output policy rejected provider output."""


@dataclass(frozen=True)
class ModelResult:
    text: str
    input_tokens: int
    output_tokens: int


class LLMAdapter(Protocol):
    async def generate(self, prompt: str, scenario: Scenario, attempt: int) -> ModelResult: ...


def tokens(text: str) -> int:
    # Demonstration estimate, not a tokenizer or a billing statement.
    return max(1, math.ceil(len(text) / 4))


class FakeLLMAdapter:
    def __init__(self, model: str):
        self.model = model

    async def generate(self, prompt: str, scenario: Scenario, attempt: int) -> ModelResult:
        if scenario == "timeout":
            await asyncio.sleep(60)
        elif scenario == "slow":
            await asyncio.sleep(0.05)
        else:
            await asyncio.sleep(0.001)
        if scenario == "failure" or (scenario == "flaky" and attempt == 0):
            raise ProviderFailure("simulated provider unavailable")
        text = (
            "[blocked-output]"
            if scenario == "unsafe"
            else f"{self.model}: simulated answer for a {tokens(prompt)}-token prompt."
        )
        return ModelResult(text, tokens(prompt), tokens(text))
