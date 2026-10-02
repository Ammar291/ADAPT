# Governance knowledge corpus

Curated records of **official** Abu Dhabi / UAE government sources, with short passages
taken from each page. This is the offline seed for ADAPT's knowledge layer: it is ingested
into the RAG tables (sources → chunks → embeddings), and every governance-graph node and
relationship must cite at least one passage from here. **No passage, no relationship.**

In the database, each source record becomes a `governance_documents` version, each passage
becomes one or more `governance_chunks`, and each publisher becomes a `governance_sources` row.
See `docs/knowledge-layer.md` for the whole layer.

One YAML file per domain cluster (`residency.yaml`, `family.yaml`, `health.yaml`,
`business.yaml`, `housing_transport.yaml`, `newcomer.yaml`).

## Source priority

When several sources say the same thing, retrieval ranks them in this order:

| Rank | Family | Examples |
|---|---|---|
| 1 | Abu Dhabi Government / TAMM | `tamm.abudhabi`, `*.abudhabi.gov.ae`, Abu Dhabi government department sites (ADDED, DMT, ADM, AD Mobility, AD Police, Abu Dhabi Residents Office) |
| 2 | UAE Government portal | `u.ae` |
| 3 | ADGM | `adgm.com` |
| 4 | Health authority / official health channels | `doh.gov.ae`, `adphc.gov.ae`, `seha.ae` |
| 5 | ICP and other UAE federal authorities | `icp.gov.ae`, `mofa.gov.ae`, `tax.gov.ae`, `mohre.gov.ae` |
| 6 | Other official authority websites | any other domain on the official allowlist |

Anything outside the official allowlist (`app/domain/provenance.py`) is **never** treated as a
government requirement.

## File format

```yaml
sources:
  - key: tamm.family_residence_visa        # <publisher>.<page_slug>; lowercase [a-z0-9_.]; unique across ALL files
    title: "Issue a Residence Visa for a Family Member"   # the page's own title
    url: https://www.tamm.abudhabi/...       # final https URL (after redirects) that was actually read
    authority: authority.abu_dhabi_government  # PUBLISHER of the page (see authority keys below)
    source_type: service_page                # service_page | guidance_page | faq | regulation | portal_page | news
    language: en
    retrieved_at: 2026-09-29                 # date the page was actually read
    effective_date: null                     # ONLY if the page states an effective / issue date
    last_updated: null                       # ONLY if the page shows a "last updated" date
    topics: [family_residency, residency]    # from the topic list below
    verification: fetched                    # fetched = page content read; search_snippet = only a search-result snippet was readable
    passages:
      - key: eligibility                     # unique within this source; [a-z0-9_]
        section: "Eligibility"               # page heading the text sits under, or null
        excerpt: quote                       # quote = copied verbatim from the page; paraphrase = faithful restatement
        states_requirement: true             # true when it states a condition, document, fee-free step or prerequisite that is REQUIRED
        text: >-
          One focused fact in 1-4 sentences, exactly as the page supports it.
```

Rules:

* Only include what the page actually says. Never fill gaps from memory.
* No fees, processing times or penalty amounts (they change often and go stale silently).
* `verification: search_snippet` sources must use `excerpt: paraphrase`.
* Keep passages small and single-purpose: one eligibility rule, one document list, one
  prerequisite, one "where to apply" statement each. Retrieval and graph evidence work per passage.

### Publisher authority keys

`authority.abu_dhabi_government` (TAMM / Abu Dhabi Government portal), `authority.uae_government`
(u.ae), `authority.adgm`, `authority.doh`, `authority.adphc`, `authority.seha`, `authority.icp`,
`authority.mofa`, `authority.fta`, `authority.mohre`, `authority.added`, `authority.dmt`,
`authority.adm`, `authority.ad_mobility`, `authority.ad_police`, `authority.adro` (Abu Dhabi
Residents Office, adro.gov.ae), `authority.adrec` (Abu Dhabi Real Estate Centre, runs Tawtheeq),
`authority.tdra` (UAE PASS). New ones need a registry entry in `app/knowledge/sources.py`.

### Topics

`residency`, `family_residency`, `emirates_id`, `medical_fitness`, `health_insurance`,
`healthcare`, `company_formation`, `adgm`, `corporate_tax`, `housing`, `tenancy`, `transport`,
`driving`, `uae_pass`, `attestation`, `newcomer`, `culture`.
