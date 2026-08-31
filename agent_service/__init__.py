"""Decoupled WeChat Agent service.

The service consumes the frozen Core HTTP V1 contract and owns only Agent
state.  It intentionally does not open any Core database files.
"""

from .service import AgentService, AgentSettings

__all__ = ["AgentService", "AgentSettings"]

