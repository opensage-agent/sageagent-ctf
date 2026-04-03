# sageagent-ctf

`sageagent-ctf` is a CTF-focused agent package built on top of the OpenSage
agent stack. It bundles the agent entrypoint, its default runtime
configuration, and the main sandbox image used for challenge solving.

## Project Layout

- `agent/agent.py`: the CTF agent entrypoint.
- `agent/config.toml`: default model, sandbox, MCP, and plugin configuration.
- `agent/main_sandbox/Dockerfile`: the main sandbox image with reversing,
  debugging, and exploitation tooling.
- `agent/main_sandbox/entrypoint.sh`: starts the bundled binary-analysis MCP
  services inside the main sandbox.

## Requirements

This project expects an environment where the following are available:

- Python and the dependencies required by the OpenSage runtime.
- `uv` for installing developer tooling such as `pre-commit`.
- The `opensage` Python package on `PYTHONPATH` or installed in the active
  environment.
- Docker or another compatible sandbox backend for building and running the
  configured sandbox images.

## Running

Run commands from the repository root so relative paths inside
`agent/config.toml` resolve correctly.

Example:

```bash
opensage web --agent ./agent
```

## Pre-commit

Install `pre-commit` with `uv` and enable the local git hook:

```bash
cd sageagent-ctf
uv tool install pre-commit
pre-commit install
```

To run all configured checks manually:

```bash
cd sageagent-ctf
pre-commit run --all-files
```

## Notes

- The default sandbox image is heavyweight and installs common CTF and reverse
  engineering tooling such as Ghidra, angr, IDA support, Playwright, and Sage.
- The default configuration expects the GDB MCP sandbox template provided by
  the surrounding OpenSage installation.
