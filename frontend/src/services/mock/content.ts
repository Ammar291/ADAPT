/**
 * Seed content for mock mode. Discover items reference real organisations by their public
 * home pages, but they are sample content, not live research, so every item is marked
 * `isSample` and shown with a "Sample" label. No dates, prices or contact details are invented.
 */
import type { EvidenceKind } from "@/domain/common";
import { domainOf } from "@/domain/common";
import type { DiscoverItem, DiscoverSection, SourceLabel } from "@/domain/discover";
import type { Approval, DocumentExtraction, DocumentKind, ExtractedField, GeneratedDocument } from "@/domain/documents";
import { hasChildren, hasSpouse, type FaithCommunity, type MoveProfile } from "@/domain/profile";
import { evidenceFor } from "./governance";
import { hoursAgo } from "./util";

interface ItemSeed {
  id: string;
  section: DiscoverSection;
  title: string;
  summary: string;
  relevance?: (p: MoveProfile) => string | null;
  source: { title: string; url: string | null; label: SourceLabel };
  evidence?: EvidenceKind;
  when?: string;
  where?: string;
  ageHours: number;
  applies?: (p: MoveProfile) => boolean;
  faith?: FaithCommunity[];
}

const founder = (p: MoveProfile) => p.moveType === "business" || p.companyTiming !== "none";

const SEEDS: ItemSeed[] = [
  // Your communities
  {
    id: "d.internations",
    section: "your_communities",
    title: "InterNations Abu Dhabi",
    summary: "A large international residents' network with regular social events and interest groups.",
    relevance: () => "A low-pressure way to meet other newcomers in your first weeks.",
    source: { title: "InterNations", url: "https://www.internations.org", label: "organization" },
    ageHours: 30,
  },
  {
    id: "d.meetup",
    section: "your_communities",
    title: "Interest groups on Meetup",
    summary: "Running clubs, book groups, language exchanges and hobby groups organised by residents.",
    relevance: (p) => (p.languages.length > 1 ? "Search for language-exchange groups in the languages you speak." : "Filter by your interests to find small, regular groups."),
    source: { title: "Meetup", url: "https://www.meetup.com", label: "community" },
    evidence: "community_web",
    ageHours: 52,
  },
  {
    id: "d.cultural_foundation",
    section: "your_communities",
    title: "Cultural Foundation",
    summary: "Abu Dhabi's arts centre, with a library, workshops and a public programme for residents.",
    relevance: (p) => (hasChildren(p.household) ? "Runs family workshops as well as talks and exhibitions." : "Workshops and talks are an easy way to meet people."),
    source: { title: "Cultural Foundation", url: "https://culturalfoundation.ae", label: "organization" },
    where: "Al Hosn, Abu Dhabi city",
    ageHours: 76,
  },
  // Faith
  {
    id: "d.grand_mosque",
    section: "faith",
    title: "Sheikh Zayed Grand Mosque",
    summary: "The country's largest mosque, open for prayer and, outside prayer times, for visitors.",
    source: { title: "Sheikh Zayed Grand Mosque Center", url: "https://www.szgmc.gov.ae", label: "official" },
    evidence: "official_guidance",
    where: "Abu Dhabi city",
    ageHours: 20,
    faith: ["islam", "all"],
  },
  {
    id: "d.abrahamic",
    section: "faith",
    title: "Abrahamic Family House",
    summary: "A mosque, a church and a synagogue on one site, each holding regular services.",
    source: { title: "Abrahamic Family House", url: "https://www.abrahamicfamilyhouse.ae", label: "organization" },
    where: "Saadiyat Island",
    ageHours: 44,
    faith: ["islam", "christianity", "judaism", "all"],
  },
  {
    id: "d.mandir",
    section: "faith",
    title: "BAPS Hindu Mandir",
    summary: "Abu Dhabi's traditional stone Hindu temple, open to worshippers and visitors.",
    source: { title: "BAPS Hindu Mandir Abu Dhabi", url: "https://www.mandir.ae", label: "organization" },
    where: "Abu Mureikhah",
    ageHours: 60,
    faith: ["hinduism", "all"],
  },
  // Professional
  {
    id: "d.hub71",
    section: "professional",
    title: "Hub71",
    summary: "Abu Dhabi's global tech ecosystem, with programmes and a community for startup founders.",
    relevance: () => "Founder-focused, with community events open beyond its incentive programme.",
    source: { title: "Hub71", url: "https://www.hub71.com", label: "organization" },
    ageHours: 18,
    applies: founder,
  },
  {
    id: "d.adio",
    section: "professional",
    title: "Abu Dhabi Investment Office (ADIO)",
    summary: "The government office that supports companies setting up and growing in Abu Dhabi.",
    relevance: () => "Useful if your company is in one of Abu Dhabi's priority sectors.",
    source: { title: "Abu Dhabi Investment Office", url: "https://www.investinabudhabi.ae", label: "official" },
    evidence: "official_guidance",
    ageHours: 40,
    applies: founder,
  },
  {
    id: "d.chamber",
    section: "professional",
    title: "Abu Dhabi Chamber",
    summary: "The emirate's chamber of commerce, with business councils and networking events.",
    relevance: (p) => (founder(p) ? "Business councils connect you with companies in your sector." : "Its events are a good way to meet people in your industry."),
    source: { title: "Abu Dhabi Chamber of Commerce and Industry", url: "https://www.abudhabichamber.ae", label: "organization" },
    ageHours: 90,
  },
  // Events
  {
    id: "d.adfw",
    section: "events",
    title: "Abu Dhabi Finance Week",
    summary: "An annual finance and investment gathering hosted by ADGM.",
    source: { title: "Abu Dhabi Finance Week", url: "https://www.adfw.com", label: "organization" },
    when: "Annual, usually in December. Check dates on the source.",
    where: "ADGM, Al Maryah Island",
    ageHours: 26,
    applies: founder,
  },
  {
    id: "d.abudhabiart",
    section: "events",
    title: "Abu Dhabi Art",
    summary: "The emirate's annual art fair, with galleries, talks and public installations.",
    source: { title: "Abu Dhabi Art", url: "https://www.abudhabiart.ae", label: "organization" },
    when: "Annual, usually in November. Check dates on the source.",
    where: "Manarat Al Saadiyat",
    ageHours: 66,
  },
  {
    id: "d.grand_prix",
    section: "events",
    title: "Formula 1 at Yas Marina",
    summary: "The season-closing Grand Prix weekend, with concerts and events across Yas Island.",
    source: { title: "Yas Marina Circuit", url: "https://www.yasmarinacircuit.com", label: "organization" },
    when: "Annual, late in the year. Check dates on the source.",
    where: "Yas Island",
    ageHours: 80,
  },
  // Culture
  {
    id: "d.etiquette",
    section: "culture",
    title: "Greetings and everyday etiquette",
    summary: "Let the other person offer a handshake, use your right hand, and dress modestly in public buildings.",
    source: { title: "Visit Abu Dhabi", url: "https://visitabudhabi.ae", label: "official" },
    evidence: "official_guidance",
    ageHours: 34,
  },
  {
    id: "d.ramadan",
    section: "culture",
    title: "What changes during Ramadan",
    summary: "Working hours are shorter, and eating or drinking in public during daylight is best avoided.",
    source: { title: "The UAE Government portal", url: "https://u.ae", label: "official" },
    evidence: "official_guidance",
    ageHours: 48,
  },
  {
    id: "d.mosque_visits",
    section: "culture",
    title: "Visiting a mosque",
    summary: "Many mosques welcome visitors outside prayer times. Cover shoulders and knees, and check the dress code first.",
    source: { title: "Sheikh Zayed Grand Mosque Center", url: "https://www.szgmc.gov.ae", label: "official" },
    evidence: "official_guidance",
    ageHours: 72,
  },
  // Surprises
  {
    id: "d.weekend",
    section: "surprises",
    title: "The weekend is Saturday and Sunday",
    summary: "Government offices work a shorter day on Friday, and Friday prayers shape midday schedules.",
    source: { title: "The UAE Government portal", url: "https://u.ae", label: "official" },
    evidence: "official_guidance",
    ageHours: 22,
  },
  {
    id: "d.heat",
    section: "surprises",
    title: "Summer rearranges the day",
    summary: "From June to September, outdoor life moves to early mornings and evenings. Plan viewings and errands around it.",
    source: { title: "National Centre of Meteorology", url: "https://www.ncm.gov.ae", label: "official" },
    evidence: "official_guidance",
    ageHours: 58,
  },
  {
    id: "d.cheques",
    section: "surprises",
    title: "Rent is often paid by cheque",
    summary: "Landlords commonly ask for rent in post-dated cheques, one to twelve per year. Order a chequebook with your account.",
    source: { title: "Newcomer experiences", url: null, label: "general_web" },
    evidence: "community_web",
    ageHours: 96,
  },
  // Starter kit
  {
    id: "d.uaepass",
    section: "starter_kit",
    title: "Set up UAE PASS and TAMM",
    summary: "UAE PASS is your digital identity for government services; TAMM is Abu Dhabi's services app.",
    relevance: () => "Most steps in your plan hand off to TAMM or ICP, which you sign in to with UAE PASS.",
    source: { title: "UAE PASS", url: "https://uaepass.ae", label: "official" },
    evidence: "official_guidance",
    ageHours: 12,
  },
  {
    id: "d.transport",
    section: "starter_kit",
    title: "Getting around by bus",
    summary: "Abu Dhabi's public buses are run by the Integrated Transport Centre. Pay with a Hafilat card.",
    source: { title: "Integrated Transport Centre", url: "https://itc.gov.ae", label: "official" },
    evidence: "official_guidance",
    ageHours: 64,
  },
  {
    id: "d.emergency",
    section: "starter_kit",
    title: "Emergency numbers",
    summary: "Police 999, ambulance 998, fire 997. Save them before you need them.",
    source: { title: "The UAE Government portal", url: "https://u.ae", label: "official" },
    evidence: "official_guidance",
    ageHours: 12,
  },
];

export function discoverCatalogue(profile: MoveProfile, faithGranted: boolean, now = new Date()): DiscoverItem[] {
  const faith = profile.faith ?? "all";
  return SEEDS.filter((seed) => {
    if (seed.section === "faith") return faithGranted && (seed.faith ?? []).some((f) => f === faith || faith === "all");
    return seed.applies ? seed.applies(profile) : true;
  }).map((seed) => ({
    id: seed.id,
    section: seed.section,
    title: seed.title,
    summary: seed.summary,
    relevance: seed.relevance?.(profile) ?? null,
    factIds: seed.relevance ? ["fact.move_type"] : [],
    source: {
      title: seed.source.title,
      url: seed.source.url,
      domain: seed.source.url ? domainOf(seed.source.url) : null,
      label: seed.source.label,
    },
    moreSources: [],
    lastCheckedAt: hoursAgo(seed.ageHours, now),
    needsRecheck: seed.ageHours > 24 * 30,
    evidenceKind: seed.evidence ?? "community_web",
    when: seed.when ?? null,
    where: seed.where ?? null,
    contacts: [],
    saved: false,
    journeyNodeId: null,
    isSample: true,
  }));
}

// --- documents -------------------------------------------------------------------------------

const field = (name: string, label: string, value: string | null, confidence: number): ExtractedField => ({
  name,
  label,
  value,
  confidence,
  needsReview: confidence < 0.8,
});

/**
 * Specimen extractions (ICAO specimen country "Utopia"). They stand in for OCR output in
 * mock mode and never contain real personal data.
 */
export function specimenExtraction(kind: DocumentKind, now = new Date()): DocumentExtraction {
  const extractedAt = now.toISOString();
  switch (kind) {
    case "passport":
      return {
        fields: [
          field("surname", "Surname", "CARTER", 0.98),
          field("given_names", "Given names", "SAM", 0.97),
          field("nationality", "Nationality", "Utopia", 0.95),
          field("date_of_birth", "Date of birth", "1988-04-12", 0.96),
          field("passport_number", "Passport number", "UT4821937", 0.93),
          field("date_of_expiry", "Expiry date", "2031-06-30", 0.97),
          field("issuing_authority", "Issuing authority", "Utopia Passport Office", 0.76),
        ],
        warnings: [],
        extractedAt,
      };
    case "marriage_certificate":
      return {
        fields: [
          field("party_1", "First party", "Sam Carter", 0.94),
          field("party_2", "Second party", "Jordan Carter", 0.88),
          field("date_of_marriage", "Date of marriage", "2019-05-18", 0.91),
          field("place_of_marriage", "Place of marriage", "Utopia City", 0.72),
          field("certificate_number", "Certificate number", "MC-2019-0847", 0.64),
          field("home_attestation", "Home-country attestation", null, 0.55),
        ],
        warnings: ["No home-country attestation stamp found. It's needed before UAE MoFA attestation."],
        extractedAt,
      };
    case "identity_document":
      return {
        fields: [
          field("document_type", "Document type", "Passport-style photo", 0.9),
          field("background", "Background", "Plain white", 0.86),
          field("meets_specification", "Meets ICP photo specification", "Likely", 0.74),
        ],
        warnings: [],
        extractedAt,
      };
    default:
      return {
        fields: [
          field("document_title", "Document title", "Untitled document", 0.62),
          field("issuer", "Issued by", null, 0.4),
          field("issue_date", "Issue date", null, 0.4),
        ],
        warnings: ["ADAPT couldn't read this document confidently. Check each field."],
        extractedAt,
      };
  }
}

// --- drafts ----------------------------------------------------------------------------------

export function draftTemplates(profile: MoveProfile, name: string | null, now = new Date()): GeneratedDocument[] {
  const me = name ?? "[Your name]";
  const at = now.toISOString();
  const spouse = hasSpouse(profile.household);
  const children = hasChildren(profile.household);
  const household = [spouse ? "my spouse" : null, children ? `${profile.childrenCount} ${profile.childrenCount === 1 ? "child" : "children"}` : null]
    .filter(Boolean)
    .join(" and ");
  const drafts: GeneratedDocument[] = [
    {
      id: "draft.insurance",
      kind: "email",
      title: "Health insurance quote request",
      bodyMarkdown: `**Subject:** Quote request: health insurance in Abu Dhabi\n\nDear team,\n\nI'm relocating to Abu Dhabi${profile.arrivalDate ? ` around ${profile.arrivalDate}` : ""} and I'm looking for health insurance that meets Department of Health requirements for residents${household ? `, covering myself and ${household}` : ""}.\n\nCould you share your plans, what each covers, and what you'd need from me to issue a policy?\n\nKind regards,\n${me}`,
      status: "draft",
      journeyNodeKey: "health.insurance",
      evidence: evidenceFor("service.health_insurance"),
      createdAt: at,
      updatedAt: at,
    },
    {
      id: "draft.viewings",
      kind: "email",
      title: "Viewing requests to letting agents",
      bodyMarkdown: `**Subject:** Viewing request\n\nHello,\n\nI'm interested in viewing the property you listed. I'm looking for a long-term lease that can be registered with Tawtheeq${profile.monthlyHousingBudgetAed ? `, with a budget of about AED ${profile.monthlyHousingBudgetAed.toLocaleString("en")} a month` : ""}.\n\nCould you suggest times for a viewing, and confirm the payment terms?\n\nThank you,\n${me}`,
      status: "draft",
      journeyNodeKey: "housing.search",
      evidence: { kind: "ai_recommendation", citations: [], confidence: null, note: "Drafted by ADAPT for your review." },
      createdAt: at,
      updatedAt: at,
    },
    {
      id: "draft.arrival_checklist",
      kind: "checklist",
      title: "Your first week in Abu Dhabi",
      bodyMarkdown:
        "- [ ] Get a UAE mobile number\n- [ ] Set up UAE PASS and the TAMM app\n- [ ] Book your medical fitness test\n- [ ] Book Emirates ID biometrics\n- [ ] Carry your passport and entry permit to each appointment\n- [ ] Shortlist two or three areas to live in",
      status: "approved",
      journeyNodeKey: null,
      evidence: { kind: "ai_recommendation", citations: [], confidence: null, note: "ADAPT's checklist from your plan." },
      createdAt: at,
      updatedAt: at,
    },
  ];
  if (spouse) {
    drafts.push(
      {
        id: "draft.attestation_letter",
        kind: "cover_letter",
        title: "Cover letter for marriage certificate attestation",
        bodyMarkdown: `To the attestation office,\n\nI request attestation of the enclosed marriage certificate for use in the United Arab Emirates, where my spouse and I are relocating.\n\nEnclosed: original marriage certificate, copies of both passports.\n\nSincerely,\n${me}`,
        status: "draft",
        journeyNodeKey: "family.home_attestation",
        evidence: evidenceFor("requirement.home_country_attestation"),
        createdAt: at,
        updatedAt: at,
      },
      {
        id: "draft.spouse_checklist",
        kind: "checklist",
        title: "Documents for your spouse's residence visa",
        bodyMarkdown:
          "- [ ] Your spouse's passport (valid 6+ months)\n- [ ] Passport-style photos\n- [ ] Marriage certificate, attested at home and by UAE MoFA\n- [ ] Your registered tenancy contract (Tawtheeq)\n- [ ] Health insurance for your spouse\n- [ ] Proof of your income\n\nConfirm the current list on ICP before applying.",
        status: "draft",
        journeyNodeKey: "family.spouse_visa",
        evidence: evidenceFor("service.family_residence_visa"),
        createdAt: at,
        updatedAt: at,
      },
    );
  }
  if (profile.moveType === "business" || profile.companyTiming !== "none") {
    drafts.push({
      id: "draft.business_summary",
      kind: "business_summary",
      title: "Business summary for banks",
      bodyMarkdown: `## ${me}'s company\n\n**Activity:** [Describe your main business activity]\n\n**Jurisdiction:** ${profile.jurisdiction === "adgm" ? "Abu Dhabi Global Market (ADGM)" : "Abu Dhabi mainland"}\n\n**Shareholders:** ${me} (100%)\n\n**Expected monthly transactions:** [Estimate]\n\n**Main customers and suppliers:** [Countries and sectors]\n\nBanks use this to review a new company account. Keep it factual and consistent with your licence.`,
      status: "draft",
      journeyNodeKey: "finance.company_bank",
      evidence: { kind: "ai_recommendation", citations: [], confidence: null, note: "Drafted by ADAPT; banks set their own requirements." },
      createdAt: at,
      updatedAt: at,
    });
  }
  return drafts;
}

// --- approvals -------------------------------------------------------------------------------

export const SIMULATION_LABEL = "DEMO / SIMULATED";

export function approvalTemplate(nodeKey: string, profile: MoveProfile, now = new Date()): Omit<Approval, "id" | "runId"> | null {
  const spouse = hasSpouse(profile.household);
  const base = {
    gate: "action_approval" as const,
    actionId: null,
    status: "pending" as const,
    journeyNodeKey: nodeKey,
    createdAt: now.toISOString(),
    decidedAt: null,
    simulationLabel: SIMULATION_LABEL,
  };
  switch (nodeKey) {
    case "health.insurance":
      return {
        ...base,
        actionKind: "communication",
        title: "Request health insurance quotes",
        summary: `Send your quote request to three insurers${spouse ? " for cover for you and your spouse" : ""}.`,
        consequences: [
          "Three insurers receive your name, email and household size.",
          "Nothing is bought. You choose a policy after comparing quotes.",
        ],
        payloadPreview: {
          To: "Three insurers you choose",
          Subject: "Quote request: health insurance in Abu Dhabi",
          Shares: "Name, email, household size, arrival month",
        },
        requiresUserAuthentication: false,
        reversible: false,
        officialUrl: null,
      };
    case "housing.search":
      return {
        ...base,
        actionKind: "communication",
        title: "Send viewing requests",
        summary: "Ask the letting agents for three shortlisted homes to arrange viewings.",
        consequences: ["Three letting agents receive your name, email and budget.", "Agents may call or message you."],
        payloadPreview: {
          To: "Letting agents for 3 shortlisted homes",
          Subject: "Viewing request",
          Shares: profile.monthlyHousingBudgetAed ? `Name, email, budget (AED ${profile.monthlyHousingBudgetAed}/month)` : "Name, email",
        },
        requiresUserAuthentication: false,
        reversible: false,
        officialUrl: null,
      };
    case "residency.medical":
      return {
        ...base,
        actionKind: "appointment",
        title: "Book your medical fitness test",
        summary: "ADAPT prepares your details for the booking page of an approved screening centre.",
        consequences: ["You choose the slot and confirm it on the official page.", "Nothing is booked until you confirm there."],
        payloadPreview: { Name: "As on your passport", Passport: "•••• 1937", Preferred: "Weekday mornings" },
        requiresUserAuthentication: false,
        reversible: true,
        officialUrl: "https://www.doh.gov.ae",
      };
    case "residency.biometrics":
      return {
        ...base,
        actionKind: "appointment",
        title: "Book Emirates ID biometrics",
        summary: "ADAPT prepares your application details for ICP's appointment service.",
        consequences: ["You sign in with UAE PASS and pick the slot yourself.", "ADAPT never sees your UAE PASS credentials."],
        payloadPreview: { Name: "As on your passport", Passport: "•••• 1937", Centre: "Nearest ICP customer happiness centre" },
        requiresUserAuthentication: true,
        reversible: true,
        officialUrl: "https://icp.gov.ae",
      };
    default:
      return null;
  }
}
