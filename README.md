[**English**](README.md) | [**中文**](README.zh-CN.md)

```
   ______      __                      __     
  / ____/___  / /___ _____ ___  ____ _/ /____ 
 / /   / __ \/ / __ `/ __ `__ \/ __ `/ __/ _ \
/ /___/ /_/ / / /_/ / / / / / / /_/ / /_/  __/
\____/\____/_/\__,_/_/ /_/ /_/\__,_/\__/\___/ 

🥤 enjoy your vibe coding with GPTs! ✨
```

# ColaMeta

ColaMeta is an AI coding workflow harness that connects ChatGPT / GPTs to local executors.

It's not another coding agent. It's a controlled workflow layer between GPTs and your local development environment: GPTs handles judgment, triage, and task design; Runner handles version planning, scope control, preview/apply, validation review, and Git closure; local executors actually read code, edit code, and run tests.

## Installation

```bash
pip3 install colameta
```

If `pip3` is not available, use venv:

```bash
python3 -m venv path/to/venv
source path/to/venv/bin/activate
pip3 install colameta
```

After installation, use the `colameta` command:

```bash
colameta /path/to/your/project --public-base-url https://your-domain.com
colameta serve /path/to/your/project --auth-mode none --open
```

## Quick Start

```bash
colameta /path/to/project source-only   # Read-only mode
colameta /path/to/project managed       # Full mode
colameta serve /path/to/project --open  # Start Web Console
```

Default local addresses:

- Web Console: `http://127.0.0.1:8799`
- MCP HTTP: `http://0.0.0.0:8765/mcp`

## Requirements

- Python 3.10+
- Git

## Safety Boundaries

- No automatic push / merge / rebase / reset / clean
- No exposure of tokens, API keys, or Bearer values
- All write operations must go through preview/apply flow
- Commits and pushes use controlled chains, never bypassing preview

## License

Open source, but **commercial use is prohibited**.
