"""Instructions and structured-output schema for live research.

Two phases per round: (1) web search, where the model searches and writes cited notes;
(2) extraction, which turns those notes into typed candidate results that may only cite
the URLs the search actually returned. Honesty rules are stated to the model here and
enforced again in code (`processing.py`).
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel

from app.research.profile import ResearchProfile
from app.research.types import ResearchCategory

CATEGORY_BRIEFS: dict[ResearchCategory, str] = {
    ResearchCategory.COMMUNITY: (
        "recognised community organisations: official associations, social and cultural "
        "centres, newcomer groups, sports and hobby clubs, volunteering groups"
    ),
    ResearchCategory.FAITH_AND_WORSHIP: (
        "places of worship and recognised faith communities, with their official websites"
    ),
    ResearchCategory.PROFESSIONAL_NETWORK: (
        "professional communities: business councils, chambers, industry associations, "
        "founder and startup programmes, professional meetups"
    ),
    ResearchCategory.EVENTS: (
        "upcoming public events: festivals, exhibitions, sports, community and networking "
        "events, with dates only when the source states them"
    ),
    ResearchCategory.CULTURE: (
        "official cultural guidance, government visitor and resident guidance, etiquette, "
        "public-behaviour laws, Ramadan considerations for everyone, local social practices"
    ),
    ResearchCategory.LIFESTYLE: (
        "everyday-life differences that surprise newcomers: working week, climate, dress in "
        "public places, photography of people, and similar practical norms"
    ),
    ResearchCategory.STARTER_KIT: (
        "first-weeks essentials for new residents: government services, ID, health "
        "insurance, transport cards, tolls, emergency numbers, utilities"
    ),
}

_HONESTY = """\
Rules:
- Abu Dhabi specifically (not Dubai or other emirates unless it clearly applies to Abu Dhabi).
- Prefer official sources: UAE and Abu Dhabi government websites for rules and guidance, and
  each organisation's own official website for communities, faith and professional groups.
- Keep these apart: binding LAW, OFFICIAL GUIDANCE, COMMUNITY INFORMATION. An ordinary web
  page is never a legal requirement.
- Never guess contact details. Mention a phone number, email or address only if it appears
  on the page you cite for it.
- Events: give dates only when the source states them, and leave out events that are over.
- Do not guess or assume anyone's religion, ethnicity or nationality.
- Only include organisations and places that appear to be currently operating."""


def search_instructions(category: ResearchCategory, today: date) -> str:
    return (
        f"You research {CATEGORY_BRIEFS[category]} in Abu Dhabi, UAE, for someone moving "
        f"there. Today is {today.isoformat()}.\n"
        "Search the web, then write concise notes: one short paragraph per specific "
        "organisation, place, event or rule, each with the page you found it on.\n"
        f"{_HONESTY}\nWrite the notes in English."
    )


def extraction_instructions(
    category: ResearchCategory, profile: ResearchProfile, today: date, max_items: int
) -> str:
    return f"""\
You turn research notes about {CATEGORY_BRIEFS[category]} in Abu Dhabi into structured \
results for one person. Today is {today.isoformat()}.

About the person (use only these facts; never guess anything else about them):
{profile.prompt_facts()}

For each distinct organisation, place, event or rule in the notes (at most {max_items}, \
most useful first):
- source_url: copy EXACTLY one URL from the SOURCES list, the page that best supports it.
  Prefer the organisation's own site or an official government page. Never invent a URL.
- supporting_urls: other URLs from the SOURCES list that confirm it (can be empty).
- claim_kind: "law" only for a binding legal rule stated on an official UAE government
  page; "official_guidance" for advisory content on an official government page;
  "community_information" for organisations, communities, events and anything else;
  "ai_recommendation" for a practical tip you synthesise from the sources.
- source_type: what the source_url page is: government, organization_site (the
  organisation's own site), community_platform, news_or_blog, other.
- summary: 1-2 factual sentences from the notes. No fees or prices.
- relevance: one sentence on why it suits THIS person, based only on the facts above. If
  none apply, say why it's useful for newcomers generally. Never mention or imply religion
  unless the person stated a faith; never mention ethnicity.
- fact_keys: which facts the relevance used, from: relocation_type, profession, interests,
  background, faith, focus, journey_goals. Empty if none.
- involves_faith: true if it is a religious organisation, place of worship or religious event.
- contacts: only website/email/phone/address values that the notes attribute to a page in
  the SOURCES list, with that page as source_url. Otherwise an empty list.
- event_start / event_end: ISO dates (YYYY-MM-DD) only if stated; otherwise null.
  event_timing: a short phrase such as "usually held in November", or null.
- Write title, summary, relevance and event_timing in {profile.language_name}. Keep
  organisation names as they are.
follow_up_queries: up to 2 web searches that would fill important gaps (for example, the
official website of an organisation that only appears on a news site). Empty if coverage
is good.
{_HONESTY}"""


# --- structured output (strict: every field required, nullable where optional) ------------


class ExtractedContact(BaseModel):
    kind: Literal["website", "email", "phone", "address"]
    value: str
    source_url: str


class ExtractedItem(BaseModel):
    title: str
    summary: str
    relevance: str
    claim_kind: Literal["law", "official_guidance", "community_information", "ai_recommendation"]
    source_url: str
    supporting_urls: list[str]
    source_type: Literal[
        "government", "organization_site", "community_platform", "news_or_blog", "other"
    ]
    fact_keys: list[str]
    involves_faith: bool
    contacts: list[ExtractedContact]
    event_start: str | None
    event_end: str | None
    event_timing: str | None


class Extraction(BaseModel):
    items: list[ExtractedItem]
    follow_up_queries: list[str]
