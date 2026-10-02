"""Source rules: canonical URLs, source labels, freshness, quality score and dedup.

The quality score ranks results internally. It is never shown to users: they see a
source label (Official / Organization / Community / General web) and when it was checked.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import date, datetime, timedelta
from urllib.parse import parse_qsl, urlencode, urlsplit

from app.domain.provenance import is_official_source
from app.research.types import ClaimedSourceType, ResearchCategory, SourceLabel

# --- URLs ------------------------------------------------------------------------------------

_TRACKING_PARAMS = frozenset(
    {
        "fbclid",
        "gclid",
        "dclid",
        "msclkid",
        "mc_cid",
        "mc_eid",
        "igshid",
        "ref",
        "ref_src",
        "srsltid",
        "si",
        "_ga",
        "_gl",
        "yclid",
        "spm",
    }
)


def canonicalize_url(url: str) -> str | None:
    """Stable identity for a web page: https, lowercase host without `www.`, no fragment,
    no tracking parameters, sorted query, no trailing slash. None if not a web URL."""
    try:
        parts = urlsplit(url.strip())
        port = parts.port
    except ValueError:
        return None
    if (
        parts.scheme.lower() not in {"http", "https"}
        or not parts.hostname
        or parts.username is not None
        or parts.password is not None
    ):
        return None
    host = parts.hostname.lower().rstrip(".")
    host = host.removeprefix("www.")
    netloc = host if port in (None, 80, 443) else f"{host}:{port}"
    path = re.sub(r"/{2,}", "/", parts.path or "")
    path = path.rstrip("/")
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=False)
        if key.lower() not in _TRACKING_PARAMS and not key.lower().startswith("utm_")
    ]
    query_string = f"?{urlencode(sorted(query))}" if query else ""
    return f"https://{netloc}{path}{query_string}"


def source_domain(url: str) -> str:
    try:
        host = (urlsplit(url).hostname or "").lower().rstrip(".")
    except ValueError:
        return ""
    return host.removeprefix("www.")


_MULTIPART_SUFFIXES = frozenset(
    {
        "gov.ae",
        "ac.ae",
        "co.ae",
        "org.ae",
        "net.ae",
        "sch.ae",
        "mil.ae",
        "co.uk",
        "org.uk",
        "gov.uk",
        "ac.uk",
        "gov.in",
        "co.in",
        "org.in",
        "nic.in",
        "com.au",
        "gov.au",
        "org.au",
        "gov.ph",
        "com.ph",
        "gov.pk",
        "com.pk",
        "gov.bd",
        "com.bd",
        "gov.eg",
        "com.eg",
    }
)


def registrable_domain(host_or_url: str) -> str:
    """Approximate eTLD+1 (`icp.gov.ae` -> `icp.gov.ae`, `events.hub71.com` -> `hub71.com`)."""
    host = source_domain(host_or_url) if "/" in host_or_url else host_or_url.lower()
    labels = host.split(".")
    if len(labels) >= 3 and ".".join(labels[-2:]) in _MULTIPART_SUFFIXES:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def is_web_url(url: str) -> bool:
    return canonicalize_url(url) is not None


# --- source labels -------------------------------------------------------------------------

_COMMUNITY_PLATFORMS = frozenset(
    {
        "meetup.com",
        "facebook.com",
        "fb.com",
        "instagram.com",
        "internations.org",
        "eventbrite.com",
        "eventbrite.ae",
        "eventbrite.co.uk",
        "reddit.com",
        "linkedin.com",
        "x.com",
        "twitter.com",
        "tiktok.com",
        "whatsapp.com",
        "chat.whatsapp.com",
        "t.me",
        "telegram.me",
        "discord.gg",
        "discord.com",
        "nextdoor.com",
        "expatwoman.com",
        "allevents.in",
        "strava.com",
        "hopasports.com",
        "groups.google.com",
    }
)

_GENERAL_WEB = frozenset(
    {
        "wikipedia.org",
        "thenationalnews.com",
        "khaleejtimes.com",
        "gulfnews.com",
        "timeoutabudhabi.com",
        "timeoutdubai.com",
        "whatson.ae",
        "tripadvisor.com",
        "medium.com",
        "blogspot.com",
        "wordpress.com",
        "expatarrivals.com",
        "gulfbusiness.com",
        "arabianbusiness.com",
        "zawya.com",
        "lovin.co",
        "bayut.com",
        "propertyfinder.ae",
        "dubizzle.com",
        "youtube.com",
        "quora.com",
        "platinumlist.net",
        "visitdubai.com",
        "wam.ae",
        "gulftoday.ae",
        "emirates247.com",
        "abudhabiworld.ae",
    }
)


def _matches(host: str, domains: frozenset[str]) -> bool:
    return any(host == d or host.endswith("." + d) for d in domains)


def classify_source(url: str, claimed: ClaimedSourceType | None = None) -> SourceLabel:
    """Domain rules first; the model's claim only decides between Organization and General
    web for domains we don't know. Official is never taken on the model's word."""
    if is_official_source(url):
        return SourceLabel.OFFICIAL
    host = source_domain(url)
    if _matches(host, _COMMUNITY_PLATFORMS):
        return SourceLabel.COMMUNITY
    if _matches(host, _GENERAL_WEB):
        return SourceLabel.GENERAL_WEB
    if claimed in (ClaimedSourceType.ORGANIZATION_SITE, ClaimedSourceType.GOVERNMENT):
        # A non-UAE government site (e.g. an embassy) is that organisation's own site.
        return SourceLabel.ORGANIZATION
    if claimed is ClaimedSourceType.COMMUNITY_PLATFORM:
        return SourceLabel.COMMUNITY
    return SourceLabel.GENERAL_WEB


# --- quality score -----------------------------------------------------------------------------

_TIER_WEIGHT: dict[SourceLabel, float] = {
    SourceLabel.OFFICIAL: 1.0,
    SourceLabel.ORGANIZATION: 0.8,
    SourceLabel.COMMUNITY: 0.55,
    SourceLabel.GENERAL_WEB: 0.4,
}

# For groups people join, the organisation's own site is as good as it gets.
_ORGANIZATION_PREFERRED = frozenset(
    {
        ResearchCategory.COMMUNITY,
        ResearchCategory.FAITH_AND_WORSHIP,
        ResearchCategory.PROFESSIONAL_NETWORK,
    }
)

RECHECK_AFTER = timedelta(days=30)


def tier_weight(label: SourceLabel, category: ResearchCategory) -> float:
    if label is SourceLabel.ORGANIZATION and category in _ORGANIZATION_PREFERRED:
        return 0.95
    return _TIER_WEIGHT[label]


def freshness_factor(retrieved_at: datetime, now: datetime) -> float:
    """1.0 for sources checked within a week, falling linearly to 0.6 at 90 days."""
    if retrieved_at > now:
        return 0.0
    age_days = max(0.0, (now - retrieved_at).total_seconds() / 86400)
    if age_days <= 7:
        return 1.0
    return max(0.6, 1.0 - (age_days - 7) / 83 * 0.4)


def quality_score(
    label: SourceLabel,
    category: ResearchCategory,
    retrieved_at: datetime,
    now: datetime,
    *,
    corroborating_sources: int = 0,
    event_date: date | None = None,
) -> float:
    """Internal ranking score in [0, 1]: source type x freshness, plus a small bonus for
    independent corroboration and for events with a stated upcoming date."""
    score = tier_weight(label, category) * freshness_factor(retrieved_at, now)
    score += min(0.1, 0.05 * max(0, corroborating_sources))
    if event_date is not None and event_date >= now.date():
        score += 0.05
    return round(min(1.0, score), 3)


def needs_recheck(retrieved_at: datetime, now: datetime) -> bool:
    return retrieved_at > now or now - retrieved_at > RECHECK_AFTER


# --- dedup ---------------------------------------------------------------------------------------

_TITLE_STOPWORDS = frozenset(
    {"the", "of", "and", "in", "a", "an", "for", "at", "on", "to", "abu", "dhabi", "uae", "ad", "&"}
)


def title_tokens(title: str) -> frozenset[str]:
    text = unicodedata.normalize("NFKC", title).casefold()
    words = re.findall(r"[\w']+", text)
    return frozenset(w for w in words if w not in _TITLE_STOPWORDS)


def normalize_title(title: str) -> str:
    return " ".join(sorted(title_tokens(title)))


def title_similarity(a: str, b: str) -> float:
    ta, tb = title_tokens(a), title_tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def same_result(url_a: str, title_a: str, url_b: str, title_b: str) -> bool:
    """Two results describe the same thing when their titles match, or when they cite the
    same page with similar titles. (Different events on one listing page stay separate.)"""
    if normalize_title(title_a) and normalize_title(title_a) == normalize_title(title_b):
        return True
    return url_a == url_b and title_similarity(title_a, title_b) >= 0.5


def dedupe_key(canonical_url: str, title: str) -> str:
    digest = hashlib.sha256(f"{canonical_url}|{normalize_title(title)}".encode()).hexdigest()
    return digest[:32]
