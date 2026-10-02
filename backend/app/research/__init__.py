"""Asynchronous Abu Dhabi research: communities, faith, networks, events, culture, daily life.

A self-contained vertical slice. The API enqueues a job and returns at once; an ARQ worker
runs the research graph (`graph.py`), which searches the web with OpenAI (or reads the
curated offline snapshot), processes and scores sources (`processing.py`) and persists
results. Progress streams to the browser as `research_*` events on the run.

Import-safe: importing `app.research.models` has no application-level side effects.
"""
