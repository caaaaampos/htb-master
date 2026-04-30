"""
Manager Agent - Planning and reasoning workflow.

Two variants available:
- ManagerAgent: Stateful, maintains chat history
- StatelessManagerAgent: Stateless, rebuilds context each turn
"""

from htb_agent.agent.droid.events import ManagerInputEvent, ManagerPlanEvent
from htb_agent.agent.manager.events import (
    ManagerContextEvent,
    ManagerPlanDetailsEvent,
    ManagerResponseEvent,
)
from htb_agent.agent.manager.manager_agent import ManagerAgent
from htb_agent.agent.manager.stateless_manager_agent import StatelessManagerAgent
from htb_agent.agent.manager.prompts import parse_manager_response

__all__ = [
    "ManagerAgent",
    "StatelessManagerAgent",
    "ManagerInputEvent",
    "ManagerPlanEvent",
    "ManagerContextEvent",
    "ManagerResponseEvent",
    "ManagerPlanDetailsEvent",
    "parse_manager_response",
]
