"""HTB Agent Terminal User Interface."""

from htb_agent.cli.tui.app import DroidrunTUI


def run_tui():
    """Run the HTB Agent TUI application."""
    app = DroidrunTUI()
    app.run()


__all__ = ["DroidrunTUI", "run_tui"]
