"""
HTB Agent Agent Module.

This module provides a ReAct agent for automating Android devices using reasoning and acting.
"""

from htb_agent.agent.droid.droid_agent import MobileAgent
from htb_agent.agent.droid.state import MobileAgentState

# HTB Agent keeps the DroidAgent public name for API compatibility.
DroidAgent = MobileAgent
DroidAgentState = MobileAgentState


__all__ = ["MobileAgent", "MobileAgentState", "DroidAgent", "DroidAgentState"]
