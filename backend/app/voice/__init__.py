"""ADAPT voice assistant (OpenAI Realtime over WebRTC) and its text fallback.

* `router`: `POST /voice/session`, `POST /voice/tool-calls`, `POST /voice/assistant`.
* `prompt`: the assistant's instructions, shared by voice and text.
* `tools`: the application tools the model may call. Every tool runs through
  `gateway.ApiGateway`, which calls ADAPT's own public API in-process as the signed-in
  user. The assistant can therefore never do more than the user's own session could, and
  it never touches the database directly.
* `guard`: binds tool calls to minted voice sessions and rate-limits them.
"""
