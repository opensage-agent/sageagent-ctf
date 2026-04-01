# sageagent-ctf

`sageagent-ctf` is a CTF-focused agent package built on top of the OpenSage
agent stack. It bundles the agent entrypoint, its default runtime
configuration, and the main sandbox image used for challenge solving.

## Project Layout

- `agent/agent.py`: the CTF agent entrypoint.
- `agent/config.toml`: default model, sandbox, MCP, and plugin configuration.
- `agent/main_sandbox/Dockerfile`: the main sandbox image with reversing,
  debugging, and exploitation tooling.

## Requirements

This project expects an environment where the following are available:

- Python and the dependencies required by the OpenSage runtime.
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

## Notes

- The default sandbox image is heavyweight and installs common CTF and reverse
  engineering tooling such as Ghidra, angr, IDA support, Playwright, and Sage.
- The default configuration expects the GDB MCP sandbox template provided by
  the surrounding OpenSage installation.
