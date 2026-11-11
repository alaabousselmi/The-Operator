"""A scripted chat model for tests: no API key, no network, same output every time.

It replays a fixed list of tool calls. With loop_forever=True it never stops asking
for tools, which is how we test that the stop rule ends the run anyway.
"""

from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult


class FakeModel(BaseChatModel):
    # Each item is one model turn: a list of (tool_name, args) pairs.
    script: list[list[tuple[str, dict]]] = []
    loop_forever: bool = False
    tokens_per_call: int = 100
    calls: int = 0  # how many times the model was invoked

    @property
    def _llm_type(self) -> str:
        return "fake"

    def bind_tools(self, tools: Any, **kwargs: Any) -> "FakeModel":
        return self  # the script already names the tools; nothing to bind

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        index = self.calls
        self.calls += 1
        usage = {
            "input_tokens": self.tokens_per_call // 2,
            "output_tokens": self.tokens_per_call - self.tokens_per_call // 2,
            "total_tokens": self.tokens_per_call,
        }
        if self.loop_forever and self.script:
            turn = self.script[index % len(self.script)]
        elif index < len(self.script):
            turn = self.script[index]
        else:
            turn = None  # script finished: answer in plain text, no tool
        if turn is None:
            message = AIMessage(content="Task finished.", usage_metadata=usage)
        else:
            tool_calls = [
                {"name": name, "args": args, "id": f"call_{index}_{n}"}
                for n, (name, args) in enumerate(turn)
            ]
            message = AIMessage(content="", tool_calls=tool_calls, usage_metadata=usage)
        return ChatResult(generations=[ChatGeneration(message=message)])
