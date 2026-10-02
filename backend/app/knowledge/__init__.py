"""Governance knowledge layer: curated official sources, retrieval, evidence and explanations.

* `corpus/` + `corpus.py`: curated records of official pages (the offline seed).
* `sources.py`: publisher registry and the source-priority order used for ranking.
* `ranking.py`, `evidence.py`: pure scoring and evidence construction.
* `evaluator.py`: pure requirement evaluation over a governance subgraph and user facts.
* `ingest.py`, `retrieval.py`, `graph_seed.py`, `graph_view.py`, `explain.py`: database-backed
  services built on the shared governance tables.
"""
