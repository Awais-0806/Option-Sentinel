"""
Alpaca MCP integration point (spec: "prepare the project for Alpaca MCP
integration", agent-facing, optional, not a core-engine dependency).

Architecture:

    AI Agent (interactive/desktop session)
        -> Alpaca MCP server
        -> Alpaca Trading API

The autonomous pipeline in core/orchestration/pipeline.py does NOT import
this module; it talks to BrokerAdapter directly (real or mock). This
module exists as the integration seam for judges/users who want to drive
OptionSentinel data through an MCP-connected agent session (e.g. asking
an MCP-aware assistant "what would OptionSentinel do with SPY right
now?"). Wiring depends on which MCP client library the operator has
installed locally, so this is intentionally left as a documented seam
rather than a hard dependency added to pyproject.toml.
"""
from __future__ import annotations


class AlpacaMCPNotConfigured(RuntimeError):
    pass


def get_mcp_client():
    raise AlpacaMCPNotConfigured(
        "Alpaca MCP is an optional, agent-facing integration path. See "
        "docs/ARCHITECTURE.md, section 'MCP Architecture', for how to wire "
        "an MCP client here once the operator has an MCP server endpoint "
        "configured. The core trading pipeline does not require this."
    )
