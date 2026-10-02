/**
 * Mock journey planner: turns a move profile and the user's progress into a journey graph.
 *
 * This only feeds mock mode. It is deliberately simple and deterministic, and it never
 * asserts fees or official processing times: durations are labelled as ADAPT estimates, and
 * every official claim cites the seeded governance node (and so the authority's own site).
 */
import type { ActionStatus, Evidence, EvidenceKind, LifeArea } from "@/domain/common";
import type { Approval, DocumentKind, UserDocument } from "@/domain/documents";
import type {
  Assumption,
  Blocker,
  BlockerKind,
  Consideration,
  Journey,
  JourneyEdge,
  JourneyNode,
  JourneyNodeKind,
  JourneyNodeStatus,
  JourneyStatus,
  NodeAction,
  NodeActionKind,
  Risk,
} from "@/domain/journey";
import { ASSUMPTION } from "@/domain/journey";
import {
  COMPANY_TIMING_LABEL,
  HOUSEHOLD_LABEL,
  HOUSING_LABEL,
  MOVE_TYPE_LABEL,
  hasChildren,
  hasSpouse,
  type MoveProfile,
} from "@/domain/profile";
import { evidenceFor } from "./governance";
import { addDays, isoDate } from "./util";

export interface PlannerProgress {
  /** Node keys the user completed. */
  done: ReadonlySet<string>;
  /** Node keys the user started. */
  inProgress: ReadonlySet<string>;
  /** Node keys whose question the user answered (premises plan, income, residency route…). */
  answered: ReadonlySet<string>;
  documents: readonly Pick<UserDocument, "kind" | "status">[];
  approvals: readonly Approval[];
  /** Drafts ADAPT prepared, by the node they belong to. */
  draftsByNode: ReadonlyMap<string, string>;
}

export interface PlannerOptions {
  journeyId: string;
  status: JourneyStatus;
  parentJourneyId?: string | null;
  now?: Date;
  createdAt?: string;
}

const URL_ = {
  tamm: "https://www.tamm.abudhabi",
  icp: "https://icp.gov.ae",
  mofa: "https://www.mofa.gov.ae",
  doh: "https://www.doh.gov.ae",
  fta: "https://tax.gov.ae",
  adgm: "https://www.adgm.com",
  uae: "https://u.ae",
  adek: "https://www.adek.gov.ae",
};

interface ActionSpec {
  kind: NodeActionKind;
  label: string;
  url?: string;
  auth?: boolean;
  documentKind?: DocumentKind;
}

interface Spec {
  key: string;
  kind: JourneyNodeKind;
  area: LifeArea;
  title: string;
  summary: string;
  why: string;
  gov?: string;
  evidence?: EvidenceKind;
  note?: string;
  authority?: string;
  url?: string;
  deps?: { key: string; anyOf?: string }[];
  requires?: string[];
  blockedBy?: string[];
  days?: number;
  /** Due date as an offset in days from arrival (negative = before arriving). */
  due?: number;
  action?: ActionSpec;
  /** A question or task only the user can resolve; cleared once answered. */
  waiting?: { kind: BlockerKind; message: string; resolution: string };
  /** Resolved by the world, not the user (e.g. arrival day, an employer's application). */
  external?: boolean;
  documentKind?: DocumentKind;
}

const d = (key: string, anyOf?: string) => ({ key, anyOf });

/** What each "answer a question" step asks. */
const QUESTIONS: Record<string, string> = {
  "business.jurisdiction": "Will you license your company on the mainland or in ADGM?",
  "business.premises": "Will you lease an office, or use an approved flexible desk?",
  "family.income": "What's your expected monthly income in AED?",
  "residency.route": "How will you hold residency until your company is set up?",
};

type ResidencyRoute = "investor" | "employer" | "family_sponsor" | "student" | "remote" | "interim";

function residencyRoute(p: MoveProfile): ResidencyRoute {
  switch (p.moveType) {
    case "business":
      return p.companyTiming === "now" ? "investor" : "interim";
    case "job":
      return "employer";
    case "family":
      return "family_sponsor";
    case "study":
      return "student";
    case "remote":
      return "remote";
  }
}

function hasCompany(p: MoveProfile): boolean {
  return p.companyTiming !== "none" || p.moveType === "business";
}

/** The node specs that apply to this profile. Order is presentation order within an area. */
function specsFor(p: MoveProfile): Spec[] {
  const specs: Spec[] = [];
  const route = residencyRoute(p);
  const company = hasCompany(p);
  const companyLater = company && (p.companyTiming === "later" || p.companyTiming === "none");
  const spouse = hasSpouse(p.household);
  const children = hasChildren(p.household);
  const bizDue = (offset: number) => (companyLater ? offset + 90 : offset);

  specs.push({
    key: "action.profile",
    kind: "action",
    area: "community",
    title: "Describe your move",
    summary: `${MOVE_TYPE_LABEL[p.moveType]}, ${HOUSEHOLD_LABEL[p.household].toLowerCase()}.`,
    why: "Everything in this plan follows from what you told ADAPT. You can change it any time in Profile.",
    evidence: "ai_recommendation",
  });

  // --- documents you hold ------------------------------------------------------------------
  specs.push({
    key: "doc.passport",
    kind: "document",
    area: "residency",
    title: "Passport, valid for 6+ months",
    summary: "Needed for almost every residency, company and housing step.",
    why: "ADAPT reads your passport details once, so you don't retype them for every application.",
    gov: "document.passport",
    documentKind: "passport",
    action: { kind: "upload_document", label: "Add your passport", documentKind: "passport" },
  });
  specs.push({
    key: "doc.photo",
    kind: "document",
    area: "residency",
    title: "Passport-style photo",
    summary: "A recent photo meeting ICP specifications, for your entry permit and Emirates ID.",
    why: "Applications are often returned for photos that don't meet the specification.",
    gov: "document.photo",
    documentKind: "identity_document",
    action: { kind: "upload_document", label: "Add a photo", documentKind: "identity_document" },
  });

  // --- business ------------------------------------------------------------------------------
  if (company) {
    if (p.jurisdiction === "undecided") {
      specs.push({
        key: "business.jurisdiction",
        kind: "task",
        area: "business",
        title: "Choose mainland or ADGM",
        summary: "Decide where to license your company. It changes which authority you deal with and your first steps.",
        why: "Every business step, and your residency through the company, depends on this choice.",
        gov: "location.adgm",
        evidence: "official_guidance",
        waiting: {
          kind: "missing_info",
          message: "ADAPT needs your choice of jurisdiction.",
          resolution: "Compare both routes in What if?, then tell ADAPT your choice.",
        },
        action: { kind: "answer_question", label: "Compare and choose" },
        due: -40,
      });
    } else {
      specs.push({
        key: "business.jurisdiction",
        kind: "action",
        area: "business",
        title: p.jurisdiction === "adgm" ? "Chose ADGM" : "Chose the mainland",
        summary:
          p.jurisdiction === "adgm"
            ? "Your company will be registered in the Abu Dhabi Global Market free zone."
            : "Your company will be licensed by ADDED on the Abu Dhabi mainland.",
        why: "This decides which authority licenses your company.",
        gov: p.jurisdiction === "adgm" ? "location.adgm" : "location.abu_dhabi_mainland",
      });
    }

    const afterChoice = p.jurisdiction === "undecided" ? [d("business.jurisdiction")] : [];
    if (p.jurisdiction === "adgm") {
      specs.push({
        key: "business.adgm_incorporation",
        kind: "task",
        area: "business",
        title: "Incorporate in ADGM",
        summary: "Register your company and get its commercial licence through the ADGM online registry.",
        why: "Your company licence unlocks the establishment card, and with it your residency and bank account.",
        gov: "service.company_registration_adgm",
        requires: ["doc.passport"],
        days: 10,
        due: bizDue(-30),
        action: { kind: "official_handoff", label: "Open the ADGM registry", url: URL_.adgm },
      });
    } else {
      specs.push({
        key: "business.trade_name",
        kind: "task",
        area: "business",
        title: "Reserve a trade name",
        summary: "Reserve your company's name before applying for initial approval.",
        why: "Your trade name appears on your licence and your company's documents.",
        gov: "service.trade_name_reservation",
        deps: afterChoice,
        days: 2,
        due: bizDue(-42),
        action: { kind: "official_handoff", label: "Open TAMM", url: URL_.tamm, auth: true },
      });
      specs.push({
        key: "business.initial_approval",
        kind: "task",
        area: "business",
        title: "Get initial approval",
        summary: "Approval in principle for your business activity and legal form.",
        why: "Confirms your activity is allowed before you commit to premises.",
        gov: "service.initial_approval",
        deps: afterChoice,
        days: 5,
        due: bizDue(-35),
        action: { kind: "official_handoff", label: "Continue on TAMM", url: URL_.tamm, auth: true },
      });
      specs.push({
        key: "business.premises",
        kind: "requirement",
        area: "business",
        title: "Registered business premises",
        summary: "Mainland licences generally need a registered office or an approved premises arrangement.",
        why: "The licence can't be issued without an address registered for the business.",
        gov: "document.commercial_tenancy_contract",
        waiting: {
          kind: "missing_info",
          message: "ADAPT doesn't know your premises plan yet.",
          resolution: "Tell ADAPT whether you'll lease an office or use an approved flexible desk.",
        },
        action: { kind: "answer_question", label: "Tell ADAPT your plan" },
        due: bizDue(-30),
      });
      specs.push({
        key: "business.licence",
        kind: "task",
        area: "business",
        title: "Issue your commercial licence",
        summary: "The final mainland licence, once initial approval and premises are in place.",
        why: "Your licence unlocks the establishment card, corporate tax registration and a company bank account.",
        gov: "service.commercial_license_mainland",
        deps: [d("business.initial_approval"), d("business.trade_name")],
        requires: ["business.premises"],
        days: 5,
        due: bizDue(-24),
        action: { kind: "official_handoff", label: "Continue on TAMM", url: URL_.tamm, auth: true },
      });
    }

    const licence = p.jurisdiction === "adgm" ? "business.adgm_incorporation" : "business.licence";
    specs.push({
      key: "business.establishment_card",
      kind: "task",
      area: "business",
      title: "Get an establishment card",
      summary: "Registers your company with immigration so it can sponsor residence visas.",
      why: "Registers your company with immigration, so it can sponsor residence visas.",
      gov: "service.establishment_card",
      deps: [d(licence, "company_licence")],
      days: 5,
      due: bizDue(-18),
      action: { kind: "official_handoff", label: "Open ICP services", url: URL_.icp, auth: true },
    });
    specs.push({
      key: "business.corporate_tax",
      kind: "task",
      area: "business",
      title: "Register for corporate tax",
      summary: "UAE companies register with the Federal Tax Authority on EmaraTax.",
      why: "Registration applies to new companies. Leaving it late can lead to penalties.",
      gov: "service.corporate_tax_registration",
      deps: [d(licence, "company_licence")],
      days: 5,
      due: bizDue(30),
      action: { kind: "official_handoff", label: "Open EmaraTax", url: URL_.fta, auth: true },
    });
  }

  // --- residency -----------------------------------------------------------------------------
  specs.push({
    key: "dep.arrival",
    kind: "dependency",
    area: "residency",
    title: "You arrive in Abu Dhabi",
    summary: p.arrivalDate ? `Planned for ${p.arrivalDate}.` : "Your arrival date is flexible.",
    why: "Medical screening and biometrics happen in person, after you arrive.",
    evidence: "ai_recommendation",
    external: true,
    due: 0,
  });

  let entryDeps: { key: string; anyOf?: string }[] = [];
  if (route === "investor") {
    // Official sources don't link the founder's visa to the establishment card, so ADAPT
    // doesn't assert an order here; the establishment card still lets the company sponsor.
    entryDeps = [];
  } else if (route === "employer" || route === "family_sponsor" || route === "student") {
    const who = { employer: "your employer", family_sponsor: "your family sponsor", student: "your university" }[route];
    specs.push({
      key: "residency.sponsor",
      kind: "dependency",
      area: "residency",
      title: `${who[0]!.toUpperCase()}${who.slice(1)} starts your visa`,
      summary: `Your entry permit and residence visa are applied for by ${who}.`,
      why: "Nothing on your residency line can move until the sponsor applies.",
      gov: "service.entry_permit_investor",
      evidence: "ai_recommendation",
      external: true,
      due: -21,
    });
    entryDeps = [d("residency.sponsor")];
  } else if (route === "remote") {
    specs.push({
      key: "residency.remote_visa",
      kind: "task",
      area: "residency",
      title: "Apply for a remote work visa",
      summary: "The UAE offers a visa for people employed by companies outside the UAE.",
      why: "It's your route to residency without a UAE employer or company.",
      evidence: "official_guidance",
      authority: "UAE Government portal",
      url: URL_.uae,
      requires: ["doc.passport"],
      days: 7,
      due: -21,
      action: { kind: "official_handoff", label: "Read the official guidance", url: URL_.uae },
    });
    entryDeps = [d("residency.remote_visa")];
  } else {
    specs.push({
      key: "residency.route",
      kind: "task",
      area: "residency",
      title: "Choose your residency route for now",
      summary: "Until your company exists, you'll need another basis for residency, such as employment or a self-employed visa.",
      why: "Your company can only sponsor your visa once it's licensed.",
      evidence: "ai_recommendation",
      note: "Confirm which routes apply to you on the official UAE portal.",
      url: URL_.uae,
      waiting: {
        kind: "missing_info",
        message: "ADAPT needs to know how you'll hold residency before your company is set up.",
        resolution: "Tell ADAPT which route you'll use, or ask the assistant to compare options.",
      },
      action: { kind: "answer_question", label: "Choose a route" },
      due: -30,
    });
    entryDeps = [d("residency.route")];
  }

  specs.push({
    key: "residency.entry_permit",
    kind: "task",
    area: "residency",
    title: route === "investor" ? "Entry permit (investor)" : "Entry permit",
    summary:
      route === "investor"
        ? "Permit to enter and complete residency formalities as the owner of your company."
        : "Permit to enter the UAE and complete your residency formalities.",
    why: "Your medical test, Emirates ID and residence visa all follow from it.",
    gov: "service.entry_permit_investor",
    deps: entryDeps,
    requires: ["doc.passport", "doc.photo"],
    days: 5,
    due: -7,
    action:
      route === "investor"
        ? { kind: "official_handoff", label: "Open ICP services", url: URL_.icp, auth: true }
        : undefined,
  });
  specs.push({
    key: "residency.medical",
    kind: "appointment",
    area: "residency",
    title: "Medical fitness test",
    summary: "Residency medical screening at an approved centre in Abu Dhabi.",
    why: "The residence visa can't be issued without a fitness certificate.",
    gov: "service.medical_fitness",
    deps: [d("residency.entry_permit"), d("dep.arrival")],
    requires: ["doc.passport"],
    days: 3,
    due: 5,
    action: { kind: "appointment", label: "Prepare a booking" },
  });
  specs.push({
    key: "residency.biometrics",
    kind: "appointment",
    area: "residency",
    title: "Emirates ID biometrics",
    summary: "Fingerprints and a photo for your Emirates ID, usually as part of the residency application.",
    why: "Banks, leases and most services ask for your Emirates ID.",
    gov: "service.emirates_id",
    deps: [d("residency.entry_permit"), d("dep.arrival")],
    requires: ["doc.passport"],
    days: 2,
    due: 7,
    action: { kind: "appointment", label: "Prepare a booking" },
  });
  specs.push({
    key: "residency.visa",
    kind: "task",
    area: "residency",
    title: "Residence visa",
    summary:
      route === "investor"
        ? "Residency for you as the company's owner, sponsored through your own company."
        : "Your UAE residency, linked to your Emirates ID.",
    why: spouse || children ? "You need your own residency before you can sponsor your family." : "It's the basis for living, banking and renting long term.",
    gov: "service.residence_visa_investor",
    deps: [d("residency.medical"), d("health.insurance")],
    days: 7,
    due: 14,
    action:
      route === "investor"
        ? { kind: "official_handoff", label: "Open ICP services", url: URL_.icp, auth: true }
        : undefined,
  });

  // --- health --------------------------------------------------------------------------------
  specs.push({
    key: "health.insurance",
    kind: "task",
    area: "health",
    title: spouse || children ? "Health insurance for your household" : "Get health insurance",
    summary: "Buy a policy that meets Abu Dhabi requirements. It's mandatory for residents and dependants.",
    why: "Required for your residence visa, and for every family member you sponsor.",
    gov: "service.health_insurance",
    days: 3,
    due: 0,
    action: { kind: "communication", label: "Review quote requests" },
  });

  // --- housing -------------------------------------------------------------------------------
  if (p.housing === "short_stay_first") {
    specs.push({
      key: "housing.short_stay",
      kind: "task",
      area: "housing",
      title: "Book a short stay",
      summary: "A serviced apartment or hotel for your first weeks while you look for a home.",
      why: spouse
        ? "Gives you time to choose, but a hotel or serviced stay usually can't be registered with Tawtheeq, so you won't have a registered address yet."
        : "Gives you time to choose an area before committing to a lease.",
      evidence: "ai_recommendation",
      days: 2,
      due: -10,
      action: { kind: "mark_done", label: "I've booked a stay" },
    });
  }
  specs.push({
    key: "housing.search",
    kind: "task",
    area: "housing",
    title: "Find a home",
    summary: p.monthlyHousingBudgetAed
      ? `Shortlist homes within about AED ${p.monthlyHousingBudgetAed.toLocaleString("en")} a month.`
      : "Shortlist areas and homes that fit your commute and budget.",
    why: "Where you live shapes your commute, schools and budget, and your lease becomes your registered address.",
    evidence: "ai_recommendation",
    deps: p.housing === "short_stay_first" ? [d("housing.short_stay")] : [],
    days: 21,
    due: p.housing === "short_stay_first" ? 21 : -5,
    action: { kind: "communication", label: "Review viewing requests" },
  });
  specs.push({
    key: "housing.lease",
    kind: "task",
    area: "housing",
    title: "Sign a long-term lease",
    summary: "Agree terms with your landlord. Rent is often paid by post-dated cheques.",
    why: "Only a long-term lease can be registered with Tawtheeq.",
    evidence: "ai_recommendation",
    deps: [d("housing.search")],
    days: 5,
    due: p.housing === "short_stay_first" ? 28 : 3,
    action: { kind: "mark_done", label: "I've signed a lease" },
  });
  specs.push({
    key: "housing.tawtheeq",
    kind: "task",
    area: "housing",
    title: "Register your lease (Tawtheeq)",
    summary: "Register your tenancy contract. It becomes your proof of accommodation.",
    why: "Your registered lease is your proof of address for utilities and many services.",
    gov: "service.tawtheeq",
    deps: [d("housing.lease")],
    requires: ["doc.passport"],
    days: 2,
    due: p.housing === "short_stay_first" ? 31 : 6,
    action: { kind: "official_handoff", label: "Open TAMM", url: URL_.tamm, auth: true },
  });

  // --- family ------------------------------------------------------------------------------
  if (spouse) {
    specs.push({
      key: "doc.marriage_certificate",
      kind: "document",
      area: "family",
      title: "Marriage certificate",
      summary: "The original certificate. It will need attestation before it's accepted in the UAE.",
      why: "The spouse visa requires it, attested in the issuing country and by UAE MoFA.",
      gov: "document.marriage_certificate_attested",
      documentKind: "marriage_certificate",
      action: { kind: "upload_document", label: "Add your certificate", documentKind: "marriage_certificate" },
    });
    specs.push({
      key: "family.home_attestation",
      kind: "task",
      area: "family",
      title: "Attest your marriage certificate at home",
      summary: "Attestation by the issuing country's authorities and the UAE embassy or consulate there.",
      why: "UAE MoFA only attests documents already attested in the issuing country. This often takes weeks.",
      gov: "requirement.home_country_attestation",
      requires: ["doc.marriage_certificate"],
      waiting: {
        kind: "attestation",
        message: "Attestation starts in the country that issued your certificate.",
        resolution: "Book attestation with the issuing authority. ADAPT drafted a cover letter for you.",
      },
      days: 21,
      due: -21,
      action: { kind: "review_draft", label: "Review the cover letter" },
    });
    specs.push({
      key: "family.mofa_attestation",
      kind: "task",
      area: "family",
      title: "UAE MoFA attestation",
      summary: "UAE attestation of your marriage certificate.",
      why: "Your spouse's visa application needs the UAE-attested certificate.",
      gov: "service.mofa_attestation",
      deps: [d("family.home_attestation")],
      days: 5,
      due: 10,
      action: { kind: "official_handoff", label: "Open TAMM", url: URL_.tamm, auth: true },
    });
    specs.push({
      key: "family.income",
      kind: "requirement",
      area: "family",
      title: "Sponsor income threshold",
      summary: "Residents sponsoring a spouse must meet a minimum monthly income, lower when accommodation is provided.",
      why: "If your income doesn't meet the threshold, the application is refused.",
      gov: "eligibility_rule.family_sponsor_income",
      waiting: {
        kind: "eligibility",
        message: "ADAPT needs your expected monthly income to check eligibility.",
        resolution: "Tell ADAPT your expected monthly income. It's only used for this check.",
      },
      action: { kind: "answer_question", label: "Check eligibility" },
    });
    specs.push({
      key: "family.spouse_visa",
      kind: "task",
      area: "family",
      title: "Sponsor your spouse's residence visa",
      summary: "Family residence visa for your spouse, sponsored by you.",
      why: "Lets your spouse live, work and access services in the UAE.",
      gov: "service.family_residence_visa",
      deps: [d("residency.visa"), d("family.mofa_attestation")],
      requires: ["family.income"],
      days: 10,
      due: p.housing === "short_stay_first" ? 45 : 30,
      action: { kind: "official_handoff", label: "Open ICP services", url: URL_.icp, auth: true },
    });
  }
  if (children) {
    specs.push({
      key: "doc.birth_certificates",
      kind: "document",
      area: "family",
      title: p.childrenCount > 1 ? "Children's birth certificates" : "Your child's birth certificate",
      summary: "Attested birth certificates for each child you sponsor.",
      why: "Needed to sponsor your children's residence visas.",
      evidence: "official_guidance",
      authority: "UAE Ministry of Foreign Affairs (MoFA)",
      url: URL_.mofa,
      documentKind: "miscellaneous",
      action: { kind: "upload_document", label: "Add certificates", documentKind: "miscellaneous" },
    });
    specs.push({
      key: "family.children_visas",
      kind: "task",
      area: "family",
      title: p.childrenCount > 1 ? "Sponsor your children's visas" : "Sponsor your child's visa",
      summary: "Residence visas for your children, sponsored by you.",
      why: "Schools ask for residency documents at enrolment.",
      gov: "service.family_residence_visa",
      deps: [d("residency.visa")],
      requires: ["doc.birth_certificates"],
      days: 10,
      due: 35,
      action: { kind: "official_handoff", label: "Open ICP services", url: URL_.icp, auth: true },
    });
    specs.push({
      key: "family.schools",
      kind: "task",
      area: "family",
      title: "Apply for school places",
      summary: "Private schools in Abu Dhabi are regulated by ADEK. Popular schools have waiting lists.",
      why: "Places fill early. Applying before you arrive avoids a gap in your children's schooling.",
      evidence: "official_guidance",
      authority: "Abu Dhabi Department of Education and Knowledge (ADEK)",
      url: URL_.adek,
      days: 30,
      due: -20,
      action: { kind: "official_handoff", label: "Open ADEK", url: URL_.adek },
    });
  }

  // --- money ---------------------------------------------------------------------------------
  specs.push({
    key: "finance.personal_bank",
    kind: "task",
    area: "finance",
    title: "Open a personal bank account",
    summary: "Most banks ask for your Emirates ID or residence visa.",
    why: "Rent, salary and utilities all run through a local account.",
    evidence: "ai_recommendation",
    deps: [d("residency.biometrics")],
    days: 7,
    due: 14,
    action: { kind: "mark_done", label: "I've opened an account" },
  });
  if (company) {
    specs.push({
      key: "finance.company_bank",
      kind: "task",
      area: "finance",
      title: "Open a company bank account",
      summary: "Banks review your licence, shareholders and business plan before opening an account.",
      why: "You can't invoice customers or pay yourself without one. Reviews can take weeks.",
      evidence: "ai_recommendation",
      deps: [d(p.jurisdiction === "adgm" ? "business.adgm_incorporation" : "business.licence")],
      days: 21,
      due: bizDue(20),
      action: { kind: "review_draft", label: "Review your business summary" },
    });
  }

  // --- daily life ----------------------------------------------------------------------------
  specs.push({
    key: "daily.sim",
    kind: "task",
    area: "daily_life",
    title: "Get a UAE mobile number",
    summary: "Many services, including UAE PASS and banks, verify you by text message.",
    why: "You'll be asked for a local number sooner than you expect.",
    evidence: "ai_recommendation",
    requires: ["doc.passport"],
    days: 1,
    due: 1,
    action: { kind: "mark_done", label: "I have a UAE number" },
  });
  specs.push({
    key: "daily.utilities",
    kind: "task",
    area: "daily_life",
    title: "Connect water and electricity",
    summary: "Set up utilities for your home once the lease is registered.",
    why: "Utility accounts use your registered lease.",
    evidence: "ai_recommendation",
    deps: [d("housing.tawtheeq")],
    days: 3,
    due: p.housing === "short_stay_first" ? 33 : 8,
    action: { kind: "official_handoff", label: "Open TAMM", url: URL_.tamm, auth: true },
  });
  specs.push({
    key: "daily.driving",
    kind: "task",
    area: "daily_life",
    title: "Convert your driving licence",
    summary: "Depending on the issuing country, you may be able to convert your licence without new lessons.",
    why: "Visitors can drive on a foreign licence for a limited time only; residents need a UAE licence.",
    evidence: "ai_recommendation",
    note: "Eligibility depends on the issuing country. Confirm on TAMM.",
    deps: [d("residency.visa")],
    days: 3,
    due: 30,
    action: { kind: "official_handoff", label: "Open TAMM", url: URL_.tamm, auth: true },
  });

  // --- community -------------------------------------------------------------------------------
  specs.push({
    key: "community.connect",
    kind: "task",
    area: "community",
    title: "Find your first community",
    summary: "Pick one group, network or event to join in your first month.",
    why: "People who connect early settle faster. ADAPT is researching options for you.",
    evidence: "ai_recommendation",
    due: 21,
    action: { kind: "navigate", label: "Open Discover" },
  });

  return specs;
}

/** Twin facts that shaped a step, keyed like the mock user graph's fact ids. */
function factIdsFor(spec: Spec): string[] {
  const facts: string[] = [];
  if (spec.area === "family") facts.push("fact.household");
  if (spec.area === "business") facts.push("fact.company_timing", "fact.jurisdiction");
  if (spec.key.startsWith("residency.")) facts.push("fact.move_type");
  if (spec.due !== undefined) facts.push("fact.arrival_date");
  if (spec.key.startsWith("housing.")) facts.push("fact.housing");
  if (spec.documentKind) facts.push(`fact.document.${spec.documentKind}`);
  return facts;
}

function documentStatus(kind: DocumentKind | undefined, docs: PlannerProgress["documents"]): JourneyNodeStatus {
  const matching = docs.filter((doc) => doc.kind === kind);
  if (matching.some((doc) => doc.status === "confirmed" || doc.status === "extracted")) return "done";
  if (matching.some((doc) => doc.status === "needs_review")) return "prepared";
  if (matching.some((doc) => doc.status === "processing" || doc.status === "uploaded")) return "in_progress";
  return "waiting_for_me";
}

function evidenceForSpec(spec: Spec): Evidence {
  if (spec.gov && !spec.evidence) return evidenceFor(spec.gov, spec.note);
  if (spec.gov && spec.evidence === "official_guidance") return evidenceFor(spec.gov, spec.note);
  const kind = spec.evidence ?? "ai_recommendation";
  const citations =
    spec.url && kind !== "ai_recommendation"
      ? [{ title: spec.authority ?? spec.title, url: spec.url, authority: spec.authority ?? null, retrievedAt: "2026-09-29T09:00:00Z", section: null, quote: null }]
      : [];
  return {
    kind,
    citations,
    confidence: null,
    note:
      spec.note ??
      (kind === "ai_recommendation"
        ? "ADAPT's suggestion based on the facts you provided."
        : "Curated summary supported by the source below."),
  };
}

function actionStatusFor(kind: NodeActionKind, nodeStatus: JourneyNodeStatus, approval: Approval | undefined): ActionStatus | null {
  if (nodeStatus === "done") return null;
  if (nodeStatus === "blocked") return "blocked";
  if (approval?.status === "pending") return "awaiting_approval";
  if (approval?.status === "approved") return "approved";
  switch (kind) {
    case "official_handoff":
      return "handoff_required";
    case "appointment":
      return "prepared";
    case "communication":
    case "review_draft":
      return "draft";
    default:
      return null;
  }
}

/** Longest path from the roots over `depends_on`/`requires`, used for ordering and layout. */
export function dependencyLevels(nodes: { key: string }[], edges: { source: string; target: string }[]): Map<string, number> {
  const deps = new Map<string, string[]>();
  for (const edge of edges) deps.set(edge.source, [...(deps.get(edge.source) ?? []), edge.target]);
  const level = new Map<string, number>();
  const visiting = new Set<string>();
  const visit = (key: string): number => {
    const known = level.get(key);
    if (known !== undefined) return known;
    if (visiting.has(key)) return 0; // cycle guard; plans are acyclic
    visiting.add(key);
    const value = Math.max(-1, ...(deps.get(key) ?? []).map(visit)) + 1;
    visiting.delete(key);
    level.set(key, value);
    return value;
  };
  nodes.forEach((n) => visit(n.key));
  return level;
}

export function buildJourney(profile: MoveProfile, progress: PlannerProgress, options: PlannerOptions): Journey {
  const now = options.now ?? new Date();
  const arrival = profile.arrivalDate ? new Date(`${profile.arrivalDate}T09:00:00`) : addDays(now, 60);
  const specs = specsFor(profile);
  const specByKey = new Map(specs.map((s) => [s.key, s]));

  // Approval nodes come from the approvals themselves.
  const approvalsByNode = new Map<string, Approval>();
  for (const approval of progress.approvals) {
    if (approval.journeyNodeKey && specByKey.has(approval.journeyNodeKey)) {
      const current = approvalsByNode.get(approval.journeyNodeKey);
      if (!current || approval.status === "pending") approvalsByNode.set(approval.journeyNodeKey, approval);
    }
  }

  const edges: JourneyEdge[] = [];
  for (const spec of specs) {
    for (const dep of spec.deps ?? []) {
      if (specByKey.has(dep.key)) {
        edges.push({ id: `${spec.key}>${dep.key}`, source: spec.key, target: dep.key, relation: "depends_on", anyOf: dep.anyOf ?? null });
      }
    }
    for (const req of spec.requires ?? []) {
      if (specByKey.has(req)) edges.push({ id: `${spec.key}>${req}`, source: spec.key, target: req, relation: "requires", anyOf: null });
    }
    for (const blocker of spec.blockedBy ?? []) {
      if (specByKey.has(blocker)) edges.push({ id: `${spec.key}>${blocker}`, source: spec.key, target: blocker, relation: "blocked_by", anyOf: null });
    }
  }

  const levels = dependencyLevels(specs, edges);
  const ordered = [...specs].sort((a, b) => (levels.get(a.key) ?? 0) - (levels.get(b.key) ?? 0));
  const status = new Map<string, JourneyNodeStatus>();
  const blockersByKey = new Map<string, Blocker[]>();

  const isSatisfied = (key: string) => status.get(key) === "done" || status.get(key) === "not_applicable";

  for (const spec of ordered) {
    const approval = approvalsByNode.get(spec.key);
    let value: JourneyNodeStatus;
    const blockers: Blocker[] = [];

    if (progress.done.has(spec.key) || spec.key === "action.profile" || (spec.kind === "action" && spec.key !== "action.profile")) {
      value = "done";
    } else if (spec.kind === "document") {
      value = documentStatus(spec.documentKind, progress.documents);
      if (value === "waiting_for_me") {
        blockers.push({ kind: "missing_document", message: `ADAPT doesn't have your ${spec.title.toLowerCase()} yet.`, resolution: "Upload a photo or PDF in Documents.", relatedNodeKey: null });
      }
    } else if (spec.external) {
      value = spec.key === "dep.arrival" && now >= arrival ? "done" : "todo";
    } else {
      const own = edges.filter((e) => e.source === spec.key && e.relation !== "approves");
      const groups = new Map<string, boolean>();
      const unmet: JourneyEdge[] = [];
      for (const edge of own) {
        if (edge.anyOf) {
          groups.set(edge.anyOf, (groups.get(edge.anyOf) ?? false) || isSatisfied(edge.target));
          continue;
        }
        if (!isSatisfied(edge.target)) unmet.push(edge);
      }
      for (const [group, ok] of groups) {
        if (!ok) unmet.push(...own.filter((e) => e.anyOf === group).slice(0, 1));
      }

      if (unmet.length) {
        value = "blocked";
        for (const edge of unmet) {
          const target = specByKey.get(edge.target)!;
          blockers.push({
            kind:
              target.kind === "document"
                ? "missing_document"
                : target.kind === "requirement"
                  ? target.waiting?.kind === "eligibility"
                    ? "eligibility"
                    : "missing_info"
                  : "dependency",
            message:
              target.kind === "document"
                ? `Needs your ${target.title.toLowerCase()}.`
                : target.kind === "requirement"
                  ? `Needs: ${target.title.toLowerCase()}.`
                  : `Waits for "${target.title}".`,
            resolution: target.action?.label ?? null,
            relatedNodeKey: target.key,
          });
        }
      } else if (spec.waiting && !progress.answered.has(spec.key)) {
        value = "waiting_for_me";
        blockers.push({ kind: spec.waiting.kind, message: spec.waiting.message, resolution: spec.waiting.resolution, relatedNodeKey: null });
      } else if (spec.waiting && spec.kind === "requirement") {
        value = "done"; // answered requirement
      } else if (approval?.status === "pending") {
        value = "waiting_for_me";
      } else if (progress.inProgress.has(spec.key)) {
        value = "in_progress";
      } else if (spec.action?.kind === "official_handoff" || spec.action?.kind === "appointment") {
        value = "prepared";
      } else if (progress.answered.has(spec.key)) {
        value = "in_progress";
      } else {
        value = "todo";
      }
    }
    status.set(spec.key, value);
    blockersByKey.set(spec.key, blockers);
  }

  const dueOf = (spec: Spec) => (spec.due === undefined ? null : isoDate(addDays(arrival, spec.due)));

  const nodes: JourneyNode[] = specs.map((spec) => {
    const nodeStatus = status.get(spec.key)!;
    const approval = approvalsByNode.get(spec.key);
    const evidence = evidenceForSpec(spec);
    const citation = evidence.citations[0];
    const action: NodeAction | null = spec.action
      ? {
          id: `act_${spec.key}`,
          kind: spec.action.kind,
          label: spec.action.label,
          status: actionStatusFor(spec.action.kind, nodeStatus, approval),
          url: spec.action.url ?? null,
          approvalId: approval?.id ?? null,
          draftId: progress.draftsByNode.get(spec.key) ?? null,
          documentKind: spec.action.documentKind ?? null,
          requiresUserAuthentication: spec.action.auth ?? false,
          question: spec.action.kind === "answer_question" ? QUESTIONS[spec.key] ?? spec.waiting?.message ?? null : null,
        }
      : null;
    return {
      id: spec.key,
      key: spec.key,
      kind: nodeStatus === "done" && spec.kind === "task" ? "action" : spec.kind,
      title: spec.title,
      summary: spec.summary,
      whyItMatters: spec.why,
      area: spec.area,
      status: nodeStatus,
      authority: citation?.authority ?? spec.authority ?? null,
      officialUrl: spec.url ?? citation?.url ?? null,
      estimatedDays: spec.days ?? null,
      dueBy: dueOf(spec),
      completedAt: nodeStatus === "done" ? options.createdAt ?? now.toISOString() : null,
      evidence,
      blockers: blockersByKey.get(spec.key) ?? [],
      action,
      governanceKey: spec.gov ?? null,
      factIds: factIdsFor(spec),
    };
  });

  // Approval checkpoints are nodes of their own, linked to the step they gate.
  for (const [nodeKey, approval] of approvalsByNode) {
    const key = `approval.${nodeKey}`;
    const parent = specByKey.get(nodeKey)!;
    nodes.push({
      id: key,
      key,
      kind: "approval",
      title: approval.title,
      summary: approval.summary,
      whyItMatters: "ADAPT never sends, books or submits anything without your approval.",
      area: parent.area,
      status: approval.status === "pending" ? "waiting_for_me" : approval.status === "approved" ? "done" : "not_applicable",
      authority: null,
      officialUrl: null,
      estimatedDays: null,
      dueBy: null,
      completedAt: approval.decidedAt,
      evidence: { kind: "ai_recommendation", citations: [], confidence: null, note: "Prepared by ADAPT for your review." },
      blockers: [],
      action: {
        id: `act_${key}`,
        kind: approval.actionKind,
        label: approval.status === "pending" ? "Review and approve" : "View decision",
        status: approval.status === "pending" ? "awaiting_approval" : approval.status === "approved" ? "approved" : null,
        url: null,
        approvalId: approval.id,
        draftId: progress.draftsByNode.get(nodeKey) ?? null,
        documentKind: null,
        requiresUserAuthentication: approval.requiresUserAuthentication,
      },
      governanceKey: null,
      factIds: [],
    });
    edges.push({ id: `${nodeKey}>${key}`, source: nodeKey, target: key, relation: "approves", anyOf: null });
  }

  const spouse = hasSpouse(profile.household);
  const children = hasChildren(profile.household);
  const company = hasCompany(profile);
  const daysToArrival = Math.round((arrival.getTime() - now.getTime()) / 86_400_000);

  const considerations: Consideration[] = [];
  const consider = (id: string, title: string, detail: string, area: LifeArea, evidence: Evidence) =>
    considerations.push({ id, title, detail, area, evidence });
  if (spouse) {
    consider(
      "c.proof_of_address",
      "Have proof of address ready for your family's applications",
      "Sponsoring family needs adequate housing, shown by a certified lease or proof of ownership. Hotels and serviced apartments usually can't give you a registered lease, so plan your long-term home early.",
      "family",
      evidenceFor("requirement.family_accommodation"),
    );
    consider(
      "c.attestation_starts_home",
      "Attestation starts where your certificate was issued",
      "UAE MoFA only attests documents already attested in the issuing country and by the UAE embassy there. Start before you travel.",
      "family",
      evidenceFor("requirement.home_country_attestation"),
    );
  }
  if (company) {
    consider(
      "c.corporate_tax",
      "New companies register for corporate tax",
      "Registration with the Federal Tax Authority applies even before your company makes a profit.",
      "business",
      evidenceFor("service.corporate_tax_registration"),
    );
  }
  consider(
    "c.insurance",
    "Health insurance is mandatory for every resident",
    spouse || children
      ? "You'll need compliant cover for yourself and each family member you sponsor, before their visas are issued."
      : "You'll need compliant cover before your residence visa is issued.",
    "health",
    evidenceFor("service.health_insurance"),
  );
  consider(
    "c.mobile_number",
    "Most services verify you with a UAE mobile number",
    "UAE PASS, banks and delivery apps send codes by text. Getting a local number in your first days saves repeated delays.",
    "daily_life",
    { kind: "ai_recommendation", citations: [], confidence: null, note: "ADAPT's suggestion from common newcomer experience." },
  );
  if (children) {
    consider(
      "c.school_places",
      "School places fill early",
      "Popular schools keep waiting lists. Apply before you arrive, and have residency documents ready for enrolment.",
      "family",
      { kind: "official_guidance", citations: [{ title: "Abu Dhabi Department of Education and Knowledge (ADEK)", url: URL_.adek, authority: "ADEK", retrievedAt: "2026-09-29T09:00:00Z", section: null, quote: null }], confidence: null, note: "Confirm admission rules with ADEK and each school." },
    );
  }

  const risks: Risk[] = [];
  if (spouse) {
    risks.push({
      id: "r.attestation_time",
      kind: "timeline_dependency",
      resolution: "Start home-country attestation now. ADAPT drafted a cover letter.",
      title: "Attestation could delay your spouse's visa",
      detail:
        daysToArrival < 60
          ? `You arrive in ${Math.max(daysToArrival, 0)} days, and home-country attestation often takes weeks. Start it now.`
          : "Home-country attestation often takes weeks. Starting early keeps your spouse's visa on schedule.",
      severity: daysToArrival < 60 ? "blocking" : "warning",
      nodeKeys: ["family.home_attestation", "family.mofa_attestation", "family.spouse_visa"],
      evidence: evidenceFor("requirement.home_country_attestation"),
    });
    if (!progress.answered.has("family.income")) {
      risks.push({
        id: "r.sponsor_income",
        kind: "eligibility_gap",
        resolution: "Tell ADAPT your expected monthly income.",
        title: "Sponsorship depends on your income",
        detail: "The spouse visa has a minimum monthly income. Confirm yours so ADAPT can check eligibility early.",
        severity: "warning",
        nodeKeys: ["family.income", "family.spouse_visa"],
        evidence: evidenceFor("eligibility_rule.family_sponsor_income"),
      });
    }
  }
  if (spouse && profile.housing === "short_stay_first") {
    risks.push({
      id: "r.short_stay_tawtheeq",
      kind: "timeline_dependency",
      resolution: "Plan your long-term lease early, and check ICP's document list for your spouse's visa.",
      title: "A short stay leaves you without a registered address",
      detail: "Hotels and serviced apartments usually can't be registered with Tawtheeq. If your family's applications ask for proof of address, you'll need your long-term lease first.",
      severity: "warning",
      nodeKeys: ["housing.short_stay", "housing.tawtheeq", "family.spouse_visa"],
      evidence: { kind: "ai_recommendation", citations: [], confidence: null, note: "ADAPT's suggestion; confirm requirements on ICP." },
    });
  }
  if (company && residencyRoute(profile) === "investor") {
    risks.push({
      id: "r.licence_chain",
      kind: "timeline_dependency",
      resolution: "Start the trade name and initial approval as early as you can.",
      title: "Your company can't sponsor anyone until it's licensed",
      detail: "The establishment card, which lets your company sponsor residence visas, comes after your licence. Delays in licensing push it back.",
      severity: "warning",
      nodeKeys: ["business.licence", "business.establishment_card"],
      evidence: evidenceFor("service.establishment_card"),
    });
  }
  if (spouse && profile.monthlyHousingBudgetAed !== null && profile.monthlyHousingBudgetAed < 6000) {
    risks.push({
      id: "r.budget",
      kind: "eligibility_gap",
      resolution: "Look at areas further out, or raise your budget in What if?.",
      title: "Your housing budget may be tight for a family home",
      detail: "Family-sized homes in central areas often cost more. Consider areas further out, or a larger budget.",
      severity: "info",
      nodeKeys: ["housing.search"],
      evidence: { kind: "ai_recommendation", citations: [], confidence: null, note: "ADAPT's estimate; prices vary by area and season." },
    });
  }

  const goals = [
    company ? (profile.companyTiming === "later" ? "Set up your company after you settle" : `Set up your company ${profile.jurisdiction === "adgm" ? "in ADGM" : "on the mainland"}`) : null,
    "Get your residence visa",
    spouse ? "Sponsor your spouse" : null,
    children ? "Sponsor your children and find schools" : null,
    "Find and register a home",
    "Settle in and find your people",
  ].filter((g): g is string => g !== null);

  const assumptions: Assumption[] = [
    { key: ASSUMPTION.moveType, label: MOVE_TYPE_LABEL[profile.moveType], value: profile.moveType },
    { key: ASSUMPTION.arrivalDate, label: profile.arrivalDate ? `Arriving ${profile.arrivalDate}` : "Flexible arrival", value: profile.arrivalDate },
    { key: ASSUMPTION.household, label: HOUSEHOLD_LABEL[profile.household], value: profile.household },
    { key: ASSUMPTION.children, label: `${profile.childrenCount} children`, value: profile.childrenCount },
    { key: ASSUMPTION.companyTiming, label: COMPANY_TIMING_LABEL[profile.companyTiming], value: profile.companyTiming },
    { key: ASSUMPTION.jurisdiction, label: profile.jurisdiction, value: profile.jurisdiction },
    { key: ASSUMPTION.housing, label: HOUSING_LABEL[profile.housing], value: profile.housing },
    { key: ASSUMPTION.budget, label: profile.monthlyHousingBudgetAed ? `AED ${profile.monthlyHousingBudgetAed}/month` : "No budget given", value: profile.monthlyHousingBudgetAed },
    { key: ASSUMPTION.languages, label: profile.languages.join(", "), value: profile.languages },
  ];

  const created = options.createdAt ?? now.toISOString();
  return {
    id: options.journeyId,
    title: company && profile.moveType === "business" ? "Your founder move to Abu Dhabi" : "Your move to Abu Dhabi",
    status: options.status,
    goals,
    assumptions,
    nodes,
    edges,
    considerations,
    risks,
    parentJourneyId: options.parentJourneyId ?? null,
    createdAt: created,
    updatedAt: now.toISOString(),
  };
}

/** Rebuilds a profile from a journey's assumptions (for What if? defaults and Profile). */
export function profileFromAssumptions(assumptions: Assumption[], fallback: MoveProfile): MoveProfile {
  const get = (key: string) => assumptions.find((a) => a.key === key)?.value;
  return {
    ...fallback,
    moveType: (get(ASSUMPTION.moveType) as MoveProfile["moveType"]) ?? fallback.moveType,
    arrivalDate: (get(ASSUMPTION.arrivalDate) as string | null) ?? fallback.arrivalDate,
    household: (get(ASSUMPTION.household) as MoveProfile["household"]) ?? fallback.household,
    childrenCount: (get(ASSUMPTION.children) as number) ?? fallback.childrenCount,
    companyTiming: (get(ASSUMPTION.companyTiming) as MoveProfile["companyTiming"]) ?? fallback.companyTiming,
    jurisdiction: (get(ASSUMPTION.jurisdiction) as MoveProfile["jurisdiction"]) ?? fallback.jurisdiction,
    housing: (get(ASSUMPTION.housing) as MoveProfile["housing"]) ?? fallback.housing,
    monthlyHousingBudgetAed: (get(ASSUMPTION.budget) as number | null) ?? fallback.monthlyHousingBudgetAed,
    languages: (get(ASSUMPTION.languages) as string[]) ?? fallback.languages,
  };
}
