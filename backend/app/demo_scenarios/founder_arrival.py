"""The "Founder Arrival" scenario: fixed inputs for a deterministic hackathon run.

Everything here is input. The plan, the facts, the findings, the research and the what-if
all come from the real pipeline (see docs/demo-founder-arrival.md).
"""

from __future__ import annotations

from app.contracts.auth import UserPreferencesUpdate
from app.contracts.profile import (
    HouseholdMemberIn,
    OnboardingProfileRequest,
    ProfileFields,
    UserGoalIn,
    UserPreferenceIn,
)
from app.demo_scenarios.contracts import (
    DemoScenarioOut,
    ScenarioActOut,
    ScenarioChange,
    ScenarioDocumentOut,
    ScenarioFact,
    ScenarioJourneyIn,
    ScenarioPersonaOut,
    ScenarioResearchGroup,
    ScenarioResearchIn,
    ScenarioRoleOut,
    ScenarioWhatIfOut,
)
from app.demo_scenarios.documents import BY_KEY, PERSONA

KEY = "founder-arrival"

# The founder states his goals, household, languages and community wishes. Nationality,
# the spouse's date of birth and the company come from the documents, never from here; he
# confirms what ADAPT read from each one (POST /documents/{id}/review), which is what lets
# his nationality personalise community research.
ONBOARDING = OnboardingProfileRequest(
    display_name="Kabir",
    profile=ProfileFields(
        preferred_name="Kabir",
        persona="founder",
        occupation="Technology start-up founder",
        languages=["en", "hi"],
        target_city="Abu Dhabi",
    ),
    household=[
        HouseholdMemberIn(
            relationship="spouse",
            name=PERSONA.spouse_name,  # as printed on the marriage certificate
            relocation_plan="with_user",
            needs_sponsorship=True,
        )
    ],
    goals=[
        UserGoalIn(goal_type="establish_company", priority="high"),
        UserGoalIn(goal_type="residency", priority="high"),
        UserGoalIn(goal_type="find_housing"),
        UserGoalIn(goal_type="sponsor_family", priority="high"),
    ],
    preferences=[
        UserPreferenceIn(
            category="community", key="interests", value=["Indian community", "start-up founders"]
        ),
        # Stated by the persona, with faith personalisation switched on below.
        UserPreferenceIn(category="faith", key="community", value="Muslim"),
    ],
    consents=UserPreferencesUpdate(
        community_personalization="granted", faith_personalization="granted"
    ),
)

PROMPT = (
    "I'm an Indian founder relocating to Abu Dhabi with my wife to start a technology "
    "company. We need a home, and I want to understand the residency and family visa "
    "requirements."
)

_DOCUMENT_NOTES = {
    "passport": (
        ["Name, nationality, date of birth and expiry", "Machine-readable zone check digits"],
        "Nationality (India) personalises community research; the passport requirement is met.",
    ),
    "marriage_certificate": (
        [
            "Both spouses and the spouse's date of birth",
            "Date and country of marriage",
            "Home-country attestation: done; UAE attestation: not yet",
        ],
        "Adds the spouse and the family chain. India's attestation is already done, so the "
        "chain starts at the UAE mission visit.",
    ),
    "business_profile": (
        ["Company name and legal form", "Planned jurisdiction: ADGM", "Business activities"],
        "The company is planned in ADGM, so ADAPT plans ADGM incorporation instead of "
        "assuming a mainland licence.",
    ),
}


def definition(api_prefix: str = "/api") -> DemoScenarioOut:
    documents = [
        ScenarioDocumentOut(
            key=doc.key,
            kind=doc.kind,
            title=doc.title,
            filename=doc.filename,
            url=f"{api_prefix}/demo/scenarios/{KEY}/documents/{doc.key}",
            reads=_DOCUMENT_NOTES[doc.key][0],
            changes=_DOCUMENT_NOTES[doc.key][1],
        )
        for doc in BY_KEY.values()
    ]
    return DemoScenarioOut(
        key=KEY,
        title="Founder Arrival",
        tagline="An Indian founder moves to Abu Dhabi with his wife to start a tech company.",
        synthetic_notice=(
            "Kabir and Ayesha Rahman and Noorvia Labs are fictional. Their documents are "
            "synthetic and marked SPECIMEN on every page."
        ),
        persona=ScenarioPersonaOut(
            name=PERSONA.full_name,
            headline="Founder, relocating from Bengaluru with his wife",
            summary=(
                "Kabir is starting a software and AI company in Abu Dhabi. He wants a home, "
                "his residence visa, and to understand what his wife Ayesha needs to join "
                "him. He speaks English and Hindi, and asks for Indian and Muslim community "
                "recommendations."
            ),
            facts=[
                ScenarioFact(
                    label="Goals", value="Company, residency, home, sponsor spouse", source="stated"
                ),
                ScenarioFact(
                    label="Household", value="Moving with his wife, Ayesha", source="stated"
                ),
                ScenarioFact(label="Languages", value="English, Hindi", source="stated"),
                ScenarioFact(
                    label="Community",
                    value="Indian community, Muslim community (opted in)",
                    source="stated",
                ),
                ScenarioFact(label="Nationality", value="From his passport", source="document"),
                ScenarioFact(
                    label="Spouse's date of birth",
                    value="From the marriage certificate",
                    source="document",
                ),
                ScenarioFact(
                    label="Company and jurisdiction",
                    value="From the business profile",
                    source="document",
                ),
                ScenarioFact(label="Monthly income", value="Not given anywhere", source="missing"),
            ],
        ),
        onboarding=ONBOARDING,
        documents=documents,
        journey=ScenarioJourneyIn(prompt=PROMPT),
        research=ScenarioResearchIn(),
        research_groups=[
            ScenarioResearchGroup(
                key="indian_community",
                title="Indian community",
                categories=["community"],
                description="Matched to his nationality, read from the passport.",
            ),
            ScenarioResearchGroup(
                key="muslim_faith",
                title="Muslim community and faith",
                categories=["faith_and_worship"],
                description="Shown because he stated his faith and turned on faith "
                "recommendations.",
            ),
            ScenarioResearchGroup(
                key="startup",
                title="Start-up and professional community",
                categories=["professional_network"],
                description="For a technology founder relocating for business.",
            ),
            ScenarioResearchGroup(
                key="culture",
                title="Cultural guidance",
                categories=["culture"],
                description="Customs and etiquette for newcomers.",
            ),
            ScenarioResearchGroup(
                key="starter",
                title="Local starter services",
                categories=["starter_kit"],
                description="The official services every new resident uses first.",
            ),
        ],
        roles=[
            ScenarioRoleOut(
                role="company",
                label="Company",
                task_key="service.company_registration_adgm",
                note="ADGM incorporation, chosen because the business profile names ADGM.",
            ),
            ScenarioRoleOut(
                role="residence",
                label="Residence",
                task_key="service.residence_visa_investor",
                note="His own residence visa; the spouse's visa is linked to it.",
            ),
            ScenarioRoleOut(
                role="document",
                label="Document",
                task_key="service.mofa_attestation",
                note="The marriage certificate needs UAE attestation before the spouse's visa.",
            ),
            ScenarioRoleOut(
                role="family",
                label="Family",
                task_key="service.family_residence_visa@spouse",
                note="Ayesha's residence visa, sponsored by Kabir.",
            ),
            ScenarioRoleOut(
                role="appointment",
                label="Appointment",
                task_key="appointment.uae_mission_visit",
                note="The next attestation stop, at the UAE mission in India.",
            ),
            ScenarioRoleOut(
                role="official_handoff",
                label="Official handoff",
                task_key="service.sponsor_file",
                note="ADAPT prepares it; Kabir completes it himself on the official site.",
            ),
            ScenarioRoleOut(
                role="missing_information",
                label="Missing information",
                task_key="service.family_residence_visa@spouse",
                note="The sponsor's minimum-income rule needs his monthly income, which no "
                "document states. ADAPT asks instead of guessing.",
            ),
        ],
        what_if=ScenarioWhatIfOut(
            key="move_alone_first",
            title="Move alone first",
            description=(
                "Kabir moves first and Ayesha joins later. See which steps and dependencies "
                "leave the first-arrival plan. The real plan is not changed."
            ),
            changes=[ScenarioChange(key="household.move_with_spouse", value=False)],
        ),
        acts=[
            ScenarioActOut(
                key="profile",
                title="Meet the founder",
                description="What Kabir tells ADAPT, and what he leaves to his documents.",
            ),
            ScenarioActOut(
                key="documents",
                title="Documents",
                description="Each document is uploaded, read, checked and added to his "
                "private twin.",
            ),
            ScenarioActOut(
                key="plan",
                title="Settlement graph",
                description="The journey agent plans from the cited governance graph.",
            ),
            ScenarioActOut(
                key="considerations",
                title="Things you may not have considered",
                description="Findings ADAPT surfaces from the rules and his documents.",
            ),
            ScenarioActOut(
                key="research",
                title="Background research",
                description="Community and starter resources, each with its source.",
            ),
            ScenarioActOut(
                key="what_if",
                title="What if: move alone first",
                description="A simulation on a copy of the plan.",
            ),
            ScenarioActOut(
                key="actions",
                title="Action cards",
                description="What ADAPT prepared, and what still needs Kabir.",
            ),
        ],
    )
