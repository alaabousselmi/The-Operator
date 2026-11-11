"""Test setup: tests never send anything to LangSmith, whatever the machine's settings."""

import os

os.environ["LANGSMITH_TRACING"] = "false"
os.environ["LANGCHAIN_TRACING_V2"] = "false"
