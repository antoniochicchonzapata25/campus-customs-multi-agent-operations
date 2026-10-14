"""A scripted stand-in for the LLM, used only in offline tests (MOCK, not a real model).

Each agent gets a list of actions; the mock plays the next one each time that
agent asks the model for a response. This exercises the real delegation code,
real MCP server, real limits, and real audit trail without any API calls.
"""

import json
import re
from typing import Any

from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel


def tool(name: str, **args: Any) -> tuple:
    return ("tool", name, args)


def final(**output: Any) -> tuple:
    return ("final", output)


class ScriptedLLM:
    def __init__(self, script: dict[str, list[tuple]], *, repeat_last: bool = False):
        self.script = {k: list(v) for k, v in script.items()}
        self.repeat_last = repeat_last
        self.calls: list[str] = []  # agent name per model request
        self.tools_seen: dict[str, set[str]] = {}
        self.instructions_seen: dict[str, str] = {}

    def model(self) -> FunctionModel:
        return FunctionModel(self._respond, model_name="scripted-mock")

    def _respond(self, messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        agent = re.search(r"You are: (\w+)\.", info.instructions or "").group(1)
        self.calls.append(agent)
        self.tools_seen[agent] = {t.name for t in info.function_tools}
        self.instructions_seen[agent] = info.instructions or ""
        queue = self.script.get(agent) or []
        if not queue:
            raise AssertionError(f"script for {agent} ran out")
        action = queue[0] if (self.repeat_last and len(queue) == 1) else queue.pop(0)
        if action[0] == "tool":
            return ModelResponse(parts=[ToolCallPart(action[1], json.dumps(action[2]))])
        if action[0] == "final":
            return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, json.dumps(action[1]))])
        return ModelResponse(parts=[TextPart(str(action))])


def specialist(agent: str, summary: str, status: str = "complete", **extra) -> tuple:
    return final(agent=agent, status=status, summary=summary, **extra)
