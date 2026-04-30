"""
Droidrun - A framework for controlling Android devices through LLM agents.
"""

import logging
from importlib.metadata import version

__version__ = version("hackthebox-agent")

# Attach a default CLILogHandler so that every consumer (CLI, TUI, SDK,
# tools-only) gets visible output without explicit setup.  CLI and TUI
# replace this with their own handler via ``configure_logging()``.
from htb_agent.log_handlers import CLILogHandler

_logger = logging.getLogger("htb_agent")
_logger.addHandler(CLILogHandler())
_logger.setLevel(logging.INFO)
_logger.propagate = False

# Import main classes for easier access
from htb_agent.agent import ResultEvent
from htb_agent.agent.droid import DroidAgent
from htb_agent.agent.utils.llm_picker import load_llm

# Import configuration classes
from htb_agent.config_manager import (
    # Agent configs
    AgentConfig,
    AppCardConfig,
    FastAgentConfig,
    CredentialsConfig,
    # Feature configs
    DeviceConfig,
    DroidrunConfig,
    ExecutorConfig,
    LLMProfile,
    LoggingConfig,
    ManagerConfig,
    SafeExecutionConfig,
    ScripterConfig,
    TelemetryConfig,
    ToolsConfig,
    TracingConfig,
)

# Import macro functionality
from htb_agent.macro import MacroPlayer, replay_macro_file, replay_macro_folder
from htb_agent.tools import AndroidDriver, DeviceDriver, RecordingDriver

# Make main components available at package level
__all__ = [
    # Agent
    "DroidAgent",
    "load_llm",
    "ResultEvent",
    # Tools / Drivers
    "DeviceDriver",
    "AndroidDriver",
    "RecordingDriver",
    # Macro
    "MacroPlayer",
    "replay_macro_file",
    "replay_macro_folder",
    # Configuration
    "DroidrunConfig",
    "AgentConfig",
    "FastAgentConfig",
    "ManagerConfig",
    "ExecutorConfig",
    "ScripterConfig",
    "AppCardConfig",
    "DeviceConfig",
    "LoggingConfig",
    "TracingConfig",
    "TelemetryConfig",
    "ToolsConfig",
    "CredentialsConfig",
    "SafeExecutionConfig",
    "LLMProfile",
]
