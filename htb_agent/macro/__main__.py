"""
Entry point for running HTB Agent macro CLI as a module.

Usage: python -m htb_agent.macro <command>
"""

from htb_agent.macro.cli import macro_cli

if __name__ == "__main__":
    macro_cli()
