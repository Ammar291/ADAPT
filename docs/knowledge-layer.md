# Governance knowledge layer

The knowledge layer (`backend/app/knowledge/`) is ADAPT's shared, source-aware model of how
Abu Dhabi's government works for a relocating founder. For any service it answers:

* who provides it, and who qualifies;
* what is required, including which documents;
* what depends on what;
* where it is accessed, and whether an appointment is involved;
* which official source supports each statement.

It has three parts:

* a curated **corpus** of official pages;
* a **governance graph** in which every node and relationship cites that corpus;
* a **retrieval and explanation** API.

The whole layer runs offline: the corpus is seeded from local files, and nothing needs web
access at runtime.

Status (2026-09-29): implemented and tested. 90 unit tests and 20 integration tests run
against Postgres with pgvector.

## 1. The rule: no citation, no fact

Every graph node and relationship names at least one passage from an official page. The seed
loader refuses anything uncited, and tests enforce the same rule twice:

* on the YAML files;
* on the database after seeding: every governance node and edge has an evidence row, and no
  cited document is unofficial.

When a researcher could not find a source for a plausible relationship, the relationship
was left out (see §8).

## 2. Source priority and trust

| Rank | Family | Publishers (registry: `sources.py`) |
|---|---|---|
| 1 | Abu Dhabi Government / TAMM | TAMM, ADDED, DMT, ADM, AD Mobility, AD Police, Abu Dhabi Residents Office, ADREC |
| 2 | UAE Government portal | u.ae |
| 3 | ADGM | adgm.com |
| 4 | Health authority / official health channels | DoH, ADPHC (SEHA registered, see §8) |
| 5 | ICP and other federal authorities | ICP, MoFA, FTA, MoHRE, TDRA |
| 6 | Other official authority websites | any allowlisted domain not in the registry |
| 7 | Unofficial | everything else: never a government requirement |

Trust is **re-derived from the URL on every read**. A page counts as official only when:

* its host is on the official-domain allowlist (`app/domain/provenance.py`); and
* its host belongs to the publisher the record claims.

A mislabelled publisher drops to rank 6, and stored labels can never raise trust.

Each passage becomes an `Evidence` object with a trust tier:

* **`authoritative_requirement`:** a current, verbatim, fully fetched official passage that
  states a requirement. All four conditions must hold.
* **`official_guidance`:** every other official passage.
* **`community_web`:** anything off the allowlist.

Confidence is calculated as `publisher trust × freshness (stale × 0.75) × paraphrase (× 0.92)
× snippet-only (× 0.8) × superseded (× 0.5) × not-yet-effective (× 0.7)`.

Each of those weaker conditions also appears as a `caveat` on the evidence, so the UI can say
"confirm on the official page".

## 3. Corpus (`knowledge/corpus/*.yaml`)

The corpus holds 60 official pages and 317 passages. Six parallel research passes read them
from the live sites on 2026-09-29, and every `quote` was checked by script against the
downloaded page text.

| Family | Pages |
|---|---|
| Abu Dhabi Government (1) | 18 |
| UAE Government (2) | 20 |
| ADGM (3) | 5 |
| Health authority (4) | 6 |
| Federal (5) | 11 |

* 54 pages were fully fetched. 6 were readable only as search snippets, which are forced to
  `paraphrase`.
* 205 passages are verbatim quotes and 112 are paraphrases. 136 passages state a requirement.
* No fees, processing times or penalty amounts are recorded, because they go stale silently.
* The format, the rules and the publisher keys are documented in `corpus/README.md`.

**Validation** (`corpus.py`) runs before anything is written:

* Missing required metadata (title, url, publisher, source type, `retrieved_at`, topics,
  passages) is a hard error. So are unknown fields, http URLs, off-allowlist URLs, and a
  publisher that doesn't own the domain.
* A snippet-only page claiming quotes, or a `retrieved_at` in the future, is also an error.
* All problems across all files are reported at once.

**Staleness** is not an error. A page checked more than 180 days ago still loads, but it is
flagged `stale`, ranked lower, has lower confidence, and is never authoritative.
`include_stale=false` or `max_age_days` filters it out.

**Versioning** (`ingest.py`) works as follows:

* A page's `content_hash` covers what it *says*, not when it was checked.
* Re-checking an unchanged page only refreshes `retrieved_at`.
* A changed page gets a new `governance_documents` version, and the old version is stamped
  `superseded_at`.
* A page dropped from the corpus is retired the same way, never deleted, so citations keep
  pointing at what they quoted.

Every chunk records its `embedding_model` (`embedder.model_id`). Chunks embedded by another
model are re-embedded on the next seed, and retrieval only compares vectors from the same
model.

### Updating the corpus

1. Read the official page and add or edit its record and passages in the right cluster file.
   Set `retrieved_at` to the date you read it.
2. Cite the new passages from `governance_graph.yaml`.
3. Run `uv run pytest tests/unit/test_knowledge_corpus.py`, then `uv run python -m app.seed`
   (or `python -m app.knowledge.seed` to reseed knowledge only).

## 4. Governance graph (`knowledge/governance_graph.yaml`)

The graph has 121 nodes and 185 relationships, citing 181 distinct passages from 51 pages.

**Entity types:**

* 31 services and 26 documents
* 20 portals and 13 authorities
* 12 requirements and 9 eligibility rules
* 5 appointments and 3 locations
* 1 dependency and 1 legal instrument

**Relations:**

| Relation | From → to | Count |
|---|---|---|
| `requires` | service → requirement / document / eligibility rule | 52 |
| `available_at` | service or appointment → portal | 43 |
| `provides` | authority → service | 30 |
| `produces` | service → document | 20 |
| `depends_on` | service → service or dependency | 18 |
| `applies_to` | eligibility rule → service | 9 |
| `may_require` | service → appointment | 6 |
| `located_in` | → location | 4 |
| `satisfied_by` | dependency → service | 2 |
| `governed_by` | → legal instrument | 1 |

Endpoint types are enforced by `graph_seed.RELATION_ENDPOINTS`. `depends_on` and
`satisfied_by` must form an acyclic graph.

**Semantics** (shared with the journey planner):

* `depends_on` means AND.
* A `dependency` node is an OR over its `satisfied_by` services. An edge's `properties.when`
  picks the path that applies: `company.jurisdiction` selects the mainland licence or ADGM
  incorporation for `dependency.company_licence`.
* A document also counts as held once the service that `produces` it is completed.

**Edge properties:**

* **`party`** is `applicant` (the default), `sponsor`, `beneficiary` or `household`. With
  `subject="spouse"`, a beneficiary edge reads that person's facts, such as
  `spouse.documents.passport`.
* **`when`** is a condition: the requirement applies only when it holds. For example, the
  medical certificate applies only when the beneficiary is 18 or older.
* **`when_party`** lets the condition read a different party's facts than the edge. For
  example, a household document may apply only when the beneficiary is a spouse.

**Node properties:**

* `condition` is the machine rule on an eligibility rule or requirement, for example the
  sponsor-income rule.
* `informational: true` marks a check the authority performs during processing, such as the
  security check or the unified Emirates ID application. It is shown to the user but never
  blocks a plan.

Legacy nodes dropped from the seed are **retired** (`valid_to`), not deleted, so private links
from user graphs keep resolving. Legacy edges are deleted.

## 5. Retrieval (`retrieval.py`, `ranking.py`)

1. **Candidates** come from two places:
   * pgvector cosine kNN via `similarity_search`, comparing only vectors from the same
     embedder;
   * a tsvector match on any expanded query term.
2. **Lexical scoring** is Okapi BM25 over the tsvector candidates, using corpus-wide document
   frequencies. A rare word ("wife", "tawtheeq") outweighs a word found on every page
   ("visa").
   * Query terms are lightly stemmed into prefixes ("families" → `famil*`), because the
     `simple` config does no stemming.
   * Terms are expanded with weights: synonyms at 0.8 (wife → spouse) and related official
     words at 0.5 (spouse → family, dependant).
3. **Filters** cover live versions, publishers, family, source type, topic, language,
   `official_only` (the default), staleness, and governance scope. Scope means passages cited
   by the given nodes or by relationships touching them.
4. **Fusion** is weighted score fusion. Each list is normalised by its best score, so a clear
   winner keeps its margin.
   * With a semantic embedder, the two lists weigh 0.5 each.
   * With the demo hashing embedder, BM25 weighs 0.75. Vectors may re-rank keyword matches
     but **never admit a passage or a node match on their own**, so gibberish returns nothing
     instead of noise.
5. **Ranking:** `score = relevance × priority weight (1.0 / .96 / .92 / .88 / .84 / .80 /
   .40) × freshness (stale .85)`, with at most 3 passages per page. Ties go to the
   higher-priority, more recently checked page.
6. **Top-k `Evidence`:** each result lists the governance keys it supports.

If the embedder is unreachable, retrieval degrades to lexical-only and says so in
`retrieval.note`.

## 6. Explain (`evaluator.py`, `explain.py`)

`POST /api/knowledge/explain {requirement, facts[], subject?, top_k}`

* `requirement` is a node key, a node id, or plain words ("I want to sponsor my wife").
* Plain words are resolved by node matching plus the nodes that the retrieved passages
  support, and the response returns alternatives.
* Facts are used for this computation only: they are never stored or logged.
* Any sensitive attribute (faith, health condition, …) is rejected with a 422.

The evaluator checks eligibility rules, requirements, documents, dependencies and
appointments. Each check is `met`, `unmet`, `unknown` or `informational`. **A missing fact is
`unknown`, never `unmet`.**

The next step is chosen in this order:

1. A failed eligibility rule leads to `review_eligibility`.
2. Unknown eligibility leads to `provide_information`.
3. Prerequisites come next. This covers dependencies and documents issued by another service.
   Undecided OR-paths come first, then sponsor-party steps, then the longest chain; the
   result is `complete_prerequisite` or `obtain_document` at the earliest undone step.
4. Open requirements, then documents to upload.
5. `book_appointment`.
6. `apply`.

Every next step is an **official handoff** that names its portal and flags UAE PASS. ADAPT
never submits anything itself.

**Highlighting.** Every check links the chain *user fact → governance requirement →
evidence → journey task*:

* `reasoning_inputs[]` holds `facts`, `node_id`/`node_key`, `edge_id`, `evidence_ids` and
  `task`.
* `links[]` flattens each chain into typed segments:
  `fact:<key> —checked_against→ node:<uuid> —evidenced_by→ evidence:<ev_id> —supports→ task:<service key>`.
* Each segment carries its `check_id` and `status`.

The id namespaces are disjoint (UUIDs, `ev_…`, fact keys, service keys), so the UI needs only
one highlight map. A missing fact appears as `provided: false`, which the UI can draw as a
hollow node.

**Fact vocabulary** (`facts.py`, shared with the journey agent and personalisation):

* `documents.<doc>`, `completed.<service>` and `meets.<requirement>`
* `finance.monthly_income_aed` and `housing.accommodation_provided`
* `company.jurisdiction`, `company.legal_form`, `company.has_resident_signatory` and
  `company.investment_aed`
* `person.age`, `person.relationship_to_sponsor`, `person.married` and `person.special_needs`
* `driving.licence_exchangeable`
* household members are prefixed, for example `spouse.person.age`

## 7. API

| Method and path | Purpose |
|---|---|
| `GET /api/knowledge/search?q=&k=&node=&authority=&family=&source_type=&topic=&official_only=&max_age_days=` | Ranked evidence plus matching governance nodes (UI search, voice) |
| `POST /api/knowledge/retrieve {query, top_k, filters, min_score}` | Ranked evidence for agents |
| `POST /api/knowledge/explain` | Graph nodes and edges, evidence, reasoning inputs, highlight links, next step |
| `GET /api/graph/governance?type=&q=&focus=&depth=&include_sources=` | The evidence-backed graph: entities, `source` nodes joined by `evidenced_by`, and every evidence object |

All of these are public routes on principal-less sessions, and RLS keeps private rows
invisible. The in-process equivalents are `retrieve()`, `explain()`, `governance_view()` and
`RequirementEvaluator`.

## 8. Known gaps and decisions for the product owner

* **SEHA (`seha.ae`) is not on the official allowlist.**
  * Two SEHA pages were read (the SEHA FAQ and the visa-screening app notice) and kept out of
    the corpus.
  * The screening centres are still cited through DoH and u.ae pages.
  * Adding `seha.ae` as an "official health channel" is a trust decision, and it belongs in
    the allowlist review.
* **TAMM pages are JavaScript-only.** TAMM service pages could not be read directly. TAMM
  facts come from u.ae, the departments' own sites and six search snippets, all marked
  `snippet_only`.
* **No standard investor or partner residence category.** ICP's service cards document no
  such category. `service.residence_visa_investor` is modelled from the generic residence
  permit, with the Green-residence investor route alongside it. No official source links the
  founder's own visa to the company's establishment card, so that edge is absent.
* **The ADGM establishment card route is unconfirmed.** Beyond "free zone companies apply
  through their free zone authority", ADGM's route for the establishment card and the
  founder's visa is unverified. ADGM's HTML pages sit behind Cloudflare, and only its PDFs
  were read.
* **Not asserted:** the eye-test booking method, the driving-licence exchange country list,
  and the Tawtheeq document list on the landlord's side. None of these is supported by a
  readable page.
* **Undated sources:** ICP service cards carry a template "last updated" date. Several health
  sources are old (a 2015 news item, the 2005 law compiled to 2010), so their passages are
  worded carefully and shown with their `retrieved_at`.
