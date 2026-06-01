"""Agent runtime: the layer that actually executes agent logic on top of litellm.

- tools.py  : the tool catalog (TOOL_REGISTRY + TOOLS_TO_FUNCTION), fixed and
              expanded from the prototype, with file tools sandboxed to workspace/.
- runner.py : run_agent(...) — builds a completion request from an agent config,
              runs the manual tool-use loop, returns (output_text, cost).
- utils.py  : encode_image helper (lifted from the prototype).
"""
