"""LangSmith tracing: see every step of a run, and its eval scores, in the LangSmith UI.

Tracing is switched on by environment variables only (see .env.example):

    LANGSMITH_TRACING=true
    LANGSMITH_API_KEY=...
    LANGSMITH_PROJECT=the-operator

With these set, LangGraph sends every model call, tool call and graph node to LangSmith
by itself. This module adds two things on top:
- traced_run: groups one whole agent run into ONE trace. A run is several graph.invoke
  calls (one per approval pause); without this they would show up as separate traces.
- log_scores: attaches the eval scores of a run to its trace (LangSmith "feedback").

Without the variables, both functions do nothing and nothing leaves the machine.
"""

from contextlib import contextmanager
from functools import lru_cache

import langsmith
from langsmith.utils import tracing_is_enabled


@contextmanager
def traced_run(name: str, tags: list[str], metadata: dict):
    """Open one LangSmith trace for a whole agent run. Yields its root run, or None
    when tracing is off."""
    if not tracing_is_enabled():
        yield None
        return
    with langsmith.trace(name=name, run_type="chain", tags=tags, metadata=metadata) as root:
        yield root


@lru_cache
def project_id(project_name: str) -> str:
    """The id of the LangSmith project (created on first use). Looked up once per process."""
    client = langsmith.Client()
    try:
        return str(client.read_project(project_name=project_name).id)
    except langsmith.utils.LangSmithNotFoundError:
        return str(client.create_project(project_name).id)


def log_scores(root, outputs: dict, scores: dict) -> None:
    """Record what the run produced, and attach each score to its trace."""
    if root is None:
        return
    root.end(outputs=outputs)
    try:
        client = langsmith.Client()
        for key, score in scores.items():
            client.create_feedback(
                root.id, key=key, score=score, trace_id=root.trace_id,
                session_id=project_id(root.session_name),
                extend_trace_retention=False,  # stay on the free base retention tier
            )
    except Exception as error:  # a tracing problem must never fail an agent or eval run
        print(f"LangSmith: scores not attached ({type(error).__name__}: {str(error)[:120]})")
