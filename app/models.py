from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Scenario = Literal["success", "slow", "timeout", "failure", "flaky", "unsafe"]


class GenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    prompt: str = Field(min_length=1, max_length=8000)
    prompt_version: Literal["v1", "v2"] = "v1"
    model: Literal["sim-primary"] = "sim-primary"
    scenario: Scenario = "success"
    fallback_scenario: Scenario = "success"
    use_cache: bool = True


class GenerateResponse(BaseModel):
    trace_id: str
    response: str
    model: str
    prompt_version: str
    status: str
    cache_hit: bool
