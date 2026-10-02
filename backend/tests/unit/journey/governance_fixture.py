"""A compact governance graph in the seed vocabulary, mirroring the primary demo
(founder relocating with a spouse). Used so journey tests don't depend on the evolving
seed file; `test_seed_compat` checks the real seed separately."""

from __future__ import annotations

from typing import Any

from app.agents.journey.governance import GovernanceSnapshot
from app.agents.journey.state import GovEdge, GovNode

_PROV = {
    "kind": "official_guidance",
    "citations": [{"source_url": "https://icp.gov.ae", "source_title": "ICP"}],
    "confidence": 0.6,
    "note": "Curated summary. Confirm on the official page.",
}


def _n(key: str, label: str, url: str | None = "https://icp.gov.ae", **props: Any) -> GovNode:
    return GovNode(
        key=key,
        type=key.split(".", 1)[0],
        label=label,
        summary=f"{label}.",
        official_url=url,
        properties=props,
        provenance=dict(_PROV, citations=[{"source_url": url, "source_title": label}])
        if url
        else None,
    )


def _e(source: str, relation: str, target: str, **props: Any) -> GovEdge:
    return GovEdge(source=source, relation=relation, target=target, properties=props)


NODES: list[GovNode] = [
    _n("authority.icp", "ICP"),
    _n("authority.added", "ADDED", "https://added.gov.ae"),
    _n("authority.adgm_ra", "ADGM Registration Authority", "https://www.adgm.com"),
    _n("authority.dmt", "DMT", "https://www.dmt.gov.ae"),
    _n("authority.mofa", "MoFA", "https://www.mofa.gov.ae"),
    _n("authority.doh", "DoH", "https://www.doh.gov.ae"),
    _n("authority.fta", "FTA", "https://tax.gov.ae"),
    _n("portal.tamm", "TAMM", "https://www.tamm.abudhabi", requires_uae_pass=True),
    _n("portal.icp_services", "ICP smart services", requires_uae_pass=True),
    _n("portal.adgm_registry", "ADGM online registry", "https://www.adgm.com"),
    _n("service.trade_name_reservation", "Reserve a trade name", "https://www.tamm.abudhabi"),
    _n("service.initial_approval", "Initial approval", "https://www.tamm.abudhabi"),
    _n(
        "service.commercial_license_mainland",
        "Commercial licence (mainland)",
        "https://www.tamm.abudhabi",
    ),
    _n("service.company_registration_adgm", "Incorporate in ADGM", "https://www.adgm.com"),
    _n("dependency.company_licence", "A company licence"),
    _n("service.establishment_card", "Establishment card"),
    _n("service.corporate_tax_registration", "Register for corporate tax", "https://tax.gov.ae"),
    _n("service.entry_permit_investor", "Entry permit (investor)"),
    _n("service.medical_fitness", "Medical fitness test", "https://www.doh.gov.ae"),
    _n("appointment.medical_screening", "Medical screening appointment", "https://www.doh.gov.ae"),
    _n("service.health_insurance", "Get health insurance", "https://www.doh.gov.ae"),
    _n("service.emirates_id", "Emirates ID biometrics"),
    _n("service.residence_visa_investor", "Residence visa (investor)"),
    _n("service.tawtheeq", "Register a tenancy contract (Tawtheeq)", "https://www.tamm.abudhabi"),
    _n("service.mofa_attestation", "Attest a foreign document (MoFA)", "https://www.mofa.gov.ae"),
    _n("service.family_residence_visa", "Sponsor your spouse's residence visa"),
    _n(
        "requirement.home_country_attestation",
        "Attestation in the issuing country",
        "https://www.mofa.gov.ae",
    ),
    _n("requirement.registered_premises", "Registered business premises", "https://added.gov.ae"),
    _n(
        "eligibility_rule.family_sponsor_income",
        "Sponsor income threshold",
        "https://u.ae",
        verify_on_official_page=True,
        condition={
            "any": [
                {"fact": "finance.monthly_income_aed", "op": "gte", "value": 4000},
                {
                    "all": [
                        {"fact": "finance.monthly_income_aed", "op": "gte", "value": 3000},
                        {"fact": "housing.accommodation_provided", "op": "eq", "value": True},
                    ]
                },
            ]
        },
    ),
    _n("document.passport", "Passport"),
    _n("document.photo", "Passport-style photo"),
    _n("document.marriage_certificate", "Marriage certificate", "https://www.mofa.gov.ae"),
    _n(
        "document.marriage_certificate_attested",
        "Attested marriage certificate",
        "https://www.mofa.gov.ae",
    ),
    _n(
        "document.tenancy_contract_registered",
        "Registered tenancy contract",
        "https://www.tamm.abudhabi",
    ),
    _n("document.commercial_license", "Commercial licence", "https://added.gov.ae"),
    _n(
        "document.medical_fitness_certificate",
        "Medical fitness certificate",
        "https://www.doh.gov.ae",
    ),
    _n("document.health_insurance_policy", "Health insurance policy", "https://www.doh.gov.ae"),
    _n("document.residence_visa", "Residence permit"),
]

EDGES: list[GovEdge] = [
    _e("authority.added", "provides", "service.trade_name_reservation"),
    _e("authority.added", "provides", "service.initial_approval"),
    _e("authority.added", "provides", "service.commercial_license_mainland"),
    _e("authority.adgm_ra", "provides", "service.company_registration_adgm"),
    _e("authority.icp", "provides", "service.establishment_card"),
    _e("authority.icp", "provides", "service.entry_permit_investor"),
    _e("authority.icp", "provides", "service.emirates_id"),
    _e("authority.icp", "provides", "service.residence_visa_investor"),
    _e("authority.icp", "provides", "service.family_residence_visa"),
    _e("authority.doh", "provides", "service.medical_fitness"),
    _e("authority.doh", "provides", "service.health_insurance"),
    _e("authority.dmt", "provides", "service.tawtheeq"),
    _e("authority.mofa", "provides", "service.mofa_attestation"),
    _e("authority.fta", "provides", "service.corporate_tax_registration"),
    _e("service.trade_name_reservation", "available_at", "portal.tamm"),
    _e("service.initial_approval", "available_at", "portal.tamm"),
    _e("service.commercial_license_mainland", "available_at", "portal.tamm"),
    _e("service.company_registration_adgm", "available_at", "portal.adgm_registry"),
    _e("service.establishment_card", "available_at", "portal.icp_services"),
    _e("service.entry_permit_investor", "available_at", "portal.icp_services"),
    _e("service.emirates_id", "available_at", "portal.icp_services"),
    _e("service.residence_visa_investor", "available_at", "portal.icp_services"),
    _e("service.family_residence_visa", "available_at", "portal.icp_services"),
    _e("service.tawtheeq", "available_at", "portal.tamm"),
    _e("service.mofa_attestation", "available_at", "portal.tamm"),
    # company
    _e("service.initial_approval", "depends_on", "service.trade_name_reservation"),
    _e("service.commercial_license_mainland", "depends_on", "service.initial_approval"),
    _e("service.commercial_license_mainland", "requires", "requirement.registered_premises"),
    _e("service.company_registration_adgm", "requires", "document.passport"),
    _e("service.commercial_license_mainland", "produces", "document.commercial_license"),
    _e("service.company_registration_adgm", "produces", "document.commercial_license"),
    _e(
        "dependency.company_licence",
        "satisfied_by",
        "service.commercial_license_mainland",
        when={"fact": "company.jurisdiction", "op": "eq", "value": "mainland"},
    ),
    _e(
        "dependency.company_licence",
        "satisfied_by",
        "service.company_registration_adgm",
        when={"fact": "company.jurisdiction", "op": "eq", "value": "adgm"},
    ),
    _e("service.establishment_card", "depends_on", "dependency.company_licence"),
    _e("service.corporate_tax_registration", "depends_on", "dependency.company_licence"),
    # founder residency
    _e("service.entry_permit_investor", "depends_on", "service.establishment_card"),
    _e("service.entry_permit_investor", "requires", "document.passport"),
    _e("service.entry_permit_investor", "requires", "document.photo"),
    _e("service.medical_fitness", "requires", "document.passport"),
    _e("service.medical_fitness", "may_require", "appointment.medical_screening"),
    _e("service.medical_fitness", "produces", "document.medical_fitness_certificate"),
    _e("service.health_insurance", "produces", "document.health_insurance_policy"),
    _e("service.emirates_id", "requires", "document.passport"),
    _e("service.residence_visa_investor", "depends_on", "service.entry_permit_investor"),
    _e("service.residence_visa_investor", "depends_on", "service.medical_fitness"),
    _e("service.residence_visa_investor", "depends_on", "service.emirates_id"),
    _e("service.residence_visa_investor", "requires", "document.health_insurance_policy"),
    _e("service.residence_visa_investor", "requires", "document.medical_fitness_certificate"),
    _e("service.residence_visa_investor", "produces", "document.residence_visa"),
    # housing
    _e("service.tawtheeq", "requires", "document.passport"),
    _e("service.tawtheeq", "produces", "document.tenancy_contract_registered"),
    # attestation
    _e("service.mofa_attestation", "requires", "requirement.home_country_attestation"),
    _e("service.mofa_attestation", "requires", "document.marriage_certificate"),
    _e("service.mofa_attestation", "produces", "document.marriage_certificate_attested"),
    # spouse sponsorship
    _e(
        "service.family_residence_visa",
        "depends_on",
        "service.residence_visa_investor",
        party="sponsor",
    ),
    _e("service.family_residence_visa", "depends_on", "service.tawtheeq", party="sponsor"),
    _e(
        "service.family_residence_visa",
        "requires",
        "document.marriage_certificate_attested",
        party="household",
    ),
    _e(
        "service.family_residence_visa",
        "requires",
        "document.tenancy_contract_registered",
        party="household",
    ),
    _e(
        "service.family_residence_visa",
        "requires",
        "document.health_insurance_policy",
        party="beneficiary",
    ),
    _e(
        "service.family_residence_visa",
        "requires",
        "document.medical_fitness_certificate",
        party="beneficiary",
    ),
    _e("service.family_residence_visa", "requires", "document.passport", party="beneficiary"),
    _e("eligibility_rule.family_sponsor_income", "applies_to", "service.family_residence_visa"),
]


def snapshot() -> GovernanceSnapshot:
    return GovernanceSnapshot.of(NODES, EDGES)
