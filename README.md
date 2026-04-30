# HTB Agent

<p align="center">
  <img src="static/htb-agent.png" alt="Hack The Box" width="180"/>
</p>

<p align="center">
  <strong>Control Android & iOS devices with natural language — Hack The Box Mobile Agent</strong>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/version-0.5.0-white?style=for-the-badge"/>
  <img src="https://img.shields.io/badge/python-3.11--3.13-white?style=for-the-badge"/>
  <img src="https://img.shields.io/badge/LLM-OpenAI-white?style=for-the-badge"/>
  <img src="https://img.shields.io/badge/license-MIT-white?style=for-the-badge"/>
</p>

---

## What is HTB Agent?

HTB Agent is a powerful framework for controlling Android and iOS devices through AI agents. It allows you to automate device interactions using natural language commands.

```bash
htb-agent run "Open WhatsApp and send a message to John"
```

## Installation

> Requires Python 3.11–3.13

```bash
pip install hackthebox-agent
```

Or from source:

```bash
git clone https://github.com/hackthebox/hackthebox-agent
cd hackthebox-agent
pip install -e .
```

## Setup

1. Install ADB (Android only):
```bash
# macOS
brew install android-platform-tools
```

2. Create `.env`:
```env
OPENAI_API_KEY=sk-your-key-here
```

3. Connect device with USB debugging enabled:
```bash
adb devices
```

## Usage

```bash
# Run a task
htb-agent run "Take a screenshot"

# List devices
htb-agent devices

# Interactive TUI
htb-agent
```

## Python API

```python
from htb_agent import DroidAgent
from htb_agent.tools import AndroidDriver

async def main():
    tools = await AndroidDriver.create()
    agent = DroidAgent(
        task="Open settings and enable dark mode",
        tools=tools,
    )
    async for event in agent.run():
        print(event)
```

## License

MIT — Original framework by the DroidRun contributors.
