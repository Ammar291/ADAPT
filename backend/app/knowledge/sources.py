"""Publisher registry and source priority.

Every page in the corpus is published by a known *publisher* (an authority or official
portal). The publisher decides the page's *source family*, and the family decides how
the page ranks against other sources that say the same thing:

    1 Abu Dhabi Government / TAMM          (tamm.abudhabi and Abu Dhabi government sites)
    2 UAE Government portal                (u.ae)
    3 ADGM                                 (adgm.com)
    4 Health authority / official health channels (DoH, ADPHC, SEHA)
    5 ICP and other UAE federal authorities
    6 Other official authority websites    (on the allowlist but not registered here)
    7 Unofficial                           (never treated as a government requirement)

Trust is always derived from the URL itself: a page is official only when its host is on
the official-domain allowlist (`app.domain.provenance`) AND belongs to the publisher it
claims. Stored metadata can never elevate a page's trust.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import urlsplit

from app.domain.provenance import is_official_source


class SourceFamily(StrEnum):
    ABU_DHABI_GOVERNMENT = "abu_dhabi_government"
    UAE_GOVERNMENT = "uae_government"
    ADGM = "adgm"
    HEALTH_AUTHORITY = "health_authority"
    FEDERAL_AUTHORITY = "federal_authority"
    OFFICIAL_AUTHORITY = "official_authority"
    UNOFFICIAL = "unofficial"


FAMILY_PRIORITY: dict[SourceFamily, int] = {
    SourceFamily.ABU_DHABI_GOVERNMENT: 1,
    SourceFamily.UAE_GOVERNMENT: 2,
    SourceFamily.ADGM: 3,
    SourceFamily.HEALTH_AUTHORITY: 4,
    SourceFamily.FEDERAL_AUTHORITY: 5,
    SourceFamily.OFFICIAL_AUTHORITY: 6,
    SourceFamily.UNOFFICIAL: 7,
}

FAMILY_LABELS: dict[SourceFamily, str] = {
    SourceFamily.ABU_DHABI_GOVERNMENT: "Abu Dhabi Government",
    SourceFamily.UAE_GOVERNMENT: "UAE Government",
    SourceFamily.ADGM: "ADGM",
    SourceFamily.HEALTH_AUTHORITY: "Health authority",
    SourceFamily.FEDERAL_AUTHORITY: "UAE federal authority",
    SourceFamily.OFFICIAL_AUTHORITY: "Official authority",
    SourceFamily.UNOFFICIAL: "Unofficial",
}


@dataclass(frozen=True, slots=True)
class Publisher:
    """An official publisher of corpus pages. `key` is its governance-graph authority key."""

    key: str
    name: str
    family: SourceFamily
    domains: tuple[str, ...]  # host suffixes this publisher controls
    base_url: str

    @property
    def priority(self) -> int:
        return FAMILY_PRIORITY[self.family]

    @property
    def site_key(self) -> str:
        """Key of the matching `governance_sources` row, e.g. 'source.icp'."""
        return "source." + self.key.removeprefix("authority.")

    def owns(self, url: str) -> bool:
        host = _host(url)
        return bool(host) and any(host == d or host.endswith("." + d) for d in self.domains)


_AD = SourceFamily.ABU_DHABI_GOVERNMENT
_FED = SourceFamily.FEDERAL_AUTHORITY
_HEALTH = SourceFamily.HEALTH_AUTHORITY

PUBLISHERS: dict[str, Publisher] = {
    p.key: p
    for p in (
        Publisher(
            "authority.abu_dhabi_government",
            "Abu Dhabi Government (TAMM)",
            _AD,
            ("tamm.abudhabi", "abudhabi.gov.ae", "abudhabi.ae"),
            "https://www.tamm.abudhabi",
        ),
        Publisher(
            "authority.added",
            "Abu Dhabi Department of Economic Development (ADDED)",
            _AD,
            ("added.gov.ae",),
            "https://www.added.gov.ae",
        ),
        Publisher(
            "authority.dmt",
            "Department of Municipalities and Transport (DMT)",
            _AD,
            ("dmt.gov.ae",),
            "https://www.dmt.gov.ae",
        ),
        Publisher(
            "authority.adm",
            "Abu Dhabi City Municipality (ADM)",
            _AD,
            ("adm.gov.ae",),
            "https://www.adm.gov.ae",
        ),
        Publisher(
            "authority.ad_mobility",
            "Abu Dhabi Mobility (AD Mobility)",
            _AD,
            ("admobility.gov.ae", "itc.gov.ae"),
            "https://admobility.gov.ae",
        ),
        Publisher(
            "authority.ad_police",
            "Abu Dhabi Police",
            _AD,
            ("adpolice.gov.ae",),
            "https://www.adpolice.gov.ae",
        ),
        Publisher(
            "authority.adro",
            "Abu Dhabi Residents Office (ADRO)",
            _AD,
            ("adro.gov.ae",),
            "https://www.adro.gov.ae",
        ),
        Publisher(
            "authority.adrec",
            "Abu Dhabi Real Estate Centre (ADREC)",
            _AD,
            ("adrec.gov.ae",),
            "https://adrec.gov.ae",
        ),
        Publisher(
            "authority.uae_government",
            "UAE Government portal (u.ae)",
            SourceFamily.UAE_GOVERNMENT,
            ("u.ae",),
            "https://u.ae",
        ),
        Publisher(
            "authority.adgm",
            "Abu Dhabi Global Market (ADGM)",
            SourceFamily.ADGM,
            ("adgm.com",),
            "https://www.adgm.com",
        ),
        Publisher(
            "authority.doh",
            "Department of Health - Abu Dhabi (DoH)",
            _HEALTH,
            ("doh.gov.ae",),
            "https://www.doh.gov.ae",
        ),
        Publisher(
            "authority.adphc",
            "Abu Dhabi Public Health Centre (ADPHC)",
            _HEALTH,
            ("adphc.gov.ae",),
            "https://www.adphc.gov.ae",
        ),
        Publisher(
            "authority.seha",
            "SEHA - Abu Dhabi Health Services Company",
            _HEALTH,
            ("seha.ae",),
            "https://www.seha.ae",
        ),
        Publisher(
            "authority.icp",
            "Federal Authority for Identity, Citizenship, Customs & Port Security (ICP)",
            _FED,
            ("icp.gov.ae",),
            "https://icp.gov.ae",
        ),
        Publisher(
            "authority.mofa",
            "UAE Ministry of Foreign Affairs (MoFA)",
            _FED,
            ("mofa.gov.ae",),
            "https://www.mofa.gov.ae",
        ),
        Publisher(
            "authority.fta",
            "Federal Tax Authority (FTA)",
            _FED,
            ("tax.gov.ae",),
            "https://tax.gov.ae",
        ),
        Publisher(
            "authority.mohre",
            "Ministry of Human Resources and Emiratisation (MoHRE)",
            _FED,
            ("mohre.gov.ae",),
            "https://www.mohre.gov.ae",
        ),
        Publisher(
            "authority.tdra",
            "Telecommunications and Digital Government Regulatory Authority (TDRA)",
            _FED,
            ("tdra.gov.ae", "uaepass.ae"),
            "https://tdra.gov.ae",
        ),
    )
}


def _host(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").lower().rstrip(".")
    except ValueError:
        return ""


@dataclass(frozen=True, slots=True)
class SourceClass:
    """How much a page at a given URL, claimed by a given publisher, is trusted."""

    publisher: Publisher | None
    family: SourceFamily
    is_official: bool

    @property
    def priority(self) -> int:
        return FAMILY_PRIORITY[self.family]


def classify_source(url: str, authority: str | None) -> SourceClass:
    """Classify a page by its URL and claimed publisher.

    * Not on the official allowlist -> UNOFFICIAL, whatever the page claims to be.
    * Official, and the claimed publisher owns the host -> that publisher's family.
    * Official but the publisher is unknown or does not own the host -> OFFICIAL_AUTHORITY
      (rank 6): a mislabelled publisher never borrows a higher rank.
    """
    if not is_official_source(url):
        return SourceClass(publisher=None, family=SourceFamily.UNOFFICIAL, is_official=False)
    publisher = PUBLISHERS.get(authority or "")
    if publisher is not None and publisher.owns(url):
        return SourceClass(publisher=publisher, family=publisher.family, is_official=True)
    return SourceClass(publisher=None, family=SourceFamily.OFFICIAL_AUTHORITY, is_official=True)


def publisher_name(authority: str | None) -> str | None:
    publisher = PUBLISHERS.get(authority or "")
    return publisher.name if publisher else authority
