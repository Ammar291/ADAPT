/**
 * Mock digital twin: the user's private graph, built from what they told ADAPT and the
 * documents they confirmed, linked to the public governance nodes it relates to.
 */
import { languageName } from "@/lib/languages";
import type { FactSource, KnowledgeEdge, KnowledgeGraph, KnowledgeNode, TwinFact } from "@/domain/graph";
import type { UserDocument } from "@/domain/documents";
import { DOCUMENT_KIND_LABEL } from "@/domain/documents";
import {
  COMPANY_TIMING_LABEL,
  HOUSEHOLD_LABEL,
  HOUSING_LABEL,
  MOVE_TYPE_LABEL,
  hasChildren,
  hasSpouse,
  type MoveProfile,
} from "@/domain/profile";
import { governanceNode } from "./governance";

function fact(value: unknown, source: FactSource, observedAt: string, confirmed = true, confidence = 1): TwinFact {
  return { value, source, sourceRef: source === "user_stated" ? "conversation:onboarding" : null, confidence, confirmedByUser: confirmed, observedAt };
}

export { languageName } from "@/lib/languages";

export function buildUserGraph(
  profile: MoveProfile,
  documents: UserDocument[],
  options: { displayName: string | null; observedAt: string; faithGranted: boolean },
): KnowledgeGraph {
  const at = options.observedAt;
  const nodes: KnowledgeNode[] = [];
  const edges: KnowledgeEdge[] = [];
  const linked = new Map<string, KnowledgeNode>();

  const add = (key: string, type: string, label: string, facts: Record<string, TwinFact> = {}, summary: string | null = null) => {
    nodes.push({ id: `twin:${key}`, key, scope: "user", type, label, summary, properties: {}, evidence: null, officialUrl: null, facts });
    return `twin:${key}`;
  };
  const link = (source: string, target: string, relation: string) => {
    edges.push({ id: `${source}>${relation}>${target}`, scope: "user", source, target, relation, label: null, anyOf: null });
  };
  const toGov = (source: string, govKey: string, relation: string) => {
    const gov = governanceNode(govKey);
    if (!gov) return;
    linked.set(gov.id, gov);
    link(source, gov.id, relation);
  };

  const you = add("person.you", "person", options.displayName ?? "You", {
    move_type: fact(MOVE_TYPE_LABEL[profile.moveType], "user_stated", at),
    household: fact(HOUSEHOLD_LABEL[profile.household], "user_stated", at),
    ...(profile.arrivalDate ? { arrival_date: fact(profile.arrivalDate, "user_stated", at) } : {}),
  });

  if (hasSpouse(profile.household)) {
    const spouse = add("person.spouse", "person", "Your spouse", { relationship: fact("Spouse", "user_stated", at) });
    link(you, spouse, "spouse_of");
    const goal = add("goal.sponsor_spouse", "goal", "Sponsor my spouse's visa");
    link(you, goal, "has_goal");
    toGov(goal, "service.family_residence_visa", "pursues");
    toGov(goal, "eligibility_rule.family_sponsor_income", "blocked_by");
  }
  if (hasChildren(profile.household)) {
    for (let i = 1; i <= Math.max(1, profile.childrenCount); i++) {
      const child = add(`person.child_${i}`, "person", profile.childrenCount > 1 ? `Child ${i}` : "Your child", {
        relationship: fact("Child", "user_stated", at),
      });
      link(child, you, "dependent_of");
    }
  }

  if (profile.moveType === "business" || profile.companyTiming !== "none") {
    const company = add(
      "organization.company",
      "organization",
      profile.jurisdiction === "adgm" ? "Your ADGM company" : "Your mainland company",
      {
        timing: fact(COMPANY_TIMING_LABEL[profile.companyTiming], "user_stated", at),
        jurisdiction: fact(profile.jurisdiction === "undecided" ? "Not decided yet" : profile.jurisdiction === "adgm" ? "ADGM" : "Mainland", "user_stated", at),
        status: fact("Planned", "system", at),
      },
    );
    link(you, company, "founder_of");
    const goal = add("goal.company", "goal", "Set up my company");
    link(you, goal, "has_goal");
    toGov(goal, profile.jurisdiction === "adgm" ? "service.company_registration_adgm" : "service.commercial_license_mainland", "pursues");
    toGov(company, profile.jurisdiction === "adgm" ? "location.adgm" : "location.abu_dhabi_mainland", "located_in");
  }

  const residency = add("goal.residency", "goal", "Get my residence visa");
  link(you, residency, "has_goal");
  toGov(residency, "service.residence_visa_investor", "pursues");

  const home = add("goal.home", "goal", "Find and register a home", {
    preference: fact(HOUSING_LABEL[profile.housing], "user_stated", at),
    ...(profile.monthlyHousingBudgetAed ? { budget: fact(`AED ${profile.monthlyHousingBudgetAed}/month`, "user_stated", at) } : {}),
  });
  link(you, home, "has_goal");
  toGov(home, "service.tawtheeq", "pursues");

  if (profile.languages.length) {
    const langs = add("preference.languages", "preference", "Languages I speak", {
      languages: fact(profile.languages.map(languageName).join(", "), "user_stated", at),
    });
    link(you, langs, "prefers");
  }
  if (options.faithGranted && profile.faith) {
    const faith = add("preference.faith", "preference", "Places of worship to include", {
      faith: fact(profile.faith === "all" ? "All faiths" : profile.faith, "user_stated", at),
    });
    link(you, faith, "prefers");
  }
  if (profile.arrivalDate) {
    const constraint = add("constraint.arrival", "constraint", `Arrive by ${profile.arrivalDate}`, {
      date: fact(profile.arrivalDate, "user_stated", at),
    });
    link(you, constraint, "constrained_by");
  }

  const govDocument: Partial<Record<string, string>> = {
    passport: "document.passport",
    marriage_certificate: "document.marriage_certificate_attested",
    identity_document: "document.photo",
    tenancy_document: "document.tenancy_contract_registered",
  };
  for (const doc of documents) {
    if (doc.status === "failed" || doc.status === "processing" || doc.status === "uploaded") continue;
    const facts: Record<string, TwinFact> = {};
    for (const f of doc.extraction?.fields ?? []) {
      if (f.value === null) continue;
      // Document numbers never leave the adapter in full.
      const masked = /number/.test(f.name) ? `•••• ${f.value.slice(-4)}` : f.value;
      facts[f.name] = fact(masked, "document_extracted", doc.extraction!.extractedAt, doc.status === "confirmed", f.confidence);
    }
    const node = add(`document.${doc.id}`, "document", DOCUMENT_KIND_LABEL[doc.kind], facts, doc.status === "confirmed" ? "Confirmed by you" : "Waiting for your review");
    link(you, node, "holds_document");
    const govKey = govDocument[doc.kind];
    if (govKey) toGov(node, govKey, doc.kind === "marriage_certificate" ? "instance_of" : "satisfies");
  }

  return finish();

  function finish(): KnowledgeGraph {
    return { nodes, edges, linkedNodes: [...linked.values()], generatedAt: at };
  }
}
