/**
 * Mock assistant: a small, deterministic intent router over the user's real plan and the
 * governance graph. It streams the same events the live assistant does (text, tool calls,
 * citations, actions, approval requests) and only states what the data supports.
 */
import type { AssistantCitation, AssistantContext, AssistantEvent, ToolCall } from "@/domain/assistant";
import type { Evidence } from "@/domain/common";
import type { Journey, JourneyNode } from "@/domain/journey";
import { blockedNodes, completion, criticalPathDays, nextActions, nodeByKey } from "@/lib/journey/analysis";
import { governanceNode, searchGovernance } from "./governance";
import { store } from "./store";
import { delay, uid } from "./util";

interface Plan {
  tools: { name: string; label: string; args: Record<string, unknown>; result: string }[];
  text: string;
  citations: AssistantCitation[];
  approvalNodeKey?: string;
  links: { to: string; label: string }[];
}

function citationsFrom(evidence: Evidence | null | undefined): AssistantCitation[] {
  if (!evidence) return [];
  return evidence.citations.map((c) => ({ ...c, kind: evidence.kind }));
}

function list(nodes: JourneyNode[]): string {
  return nodes.map((n) => `• ${n.title}${n.blockers[0] ? `: ${n.blockers[0].message}` : ""}`).join("\n");
}

const has = (text: string, ...words: string[]) => words.some((w) => text.includes(w));

function plan(text: string, journey: Journey | null): Plan {
  const q = text.toLowerCase();

  if (!journey) {
    return {
      tools: [{ name: "get_journey_status", label: "Checking your plan", args: {}, result: "No plan yet" }],
      text: "You don't have a plan yet. Tell me about your move (who's coming, when you arrive, and whether you're starting a company) and I'll build one with the official source behind every step.",
      citations: [],
      links: [{ to: "/onboarding", label: "Describe your move" }],
    };
  }

  if (has(q, "spouse", "wife", "husband", "partner", "family visa", "sponsor")) {
    const visa = nodeByKey(journey, "family.spouse_visa");
    const income = governanceNode("eligibility_rule.family_sponsor_income");
    if (!visa) {
      return {
        tools: [{ name: "get_journey_node", label: "Checking family steps", args: { key: "family.spouse_visa" }, result: "Not in your plan" }],
        text: "Your plan doesn't include sponsoring a spouse, because you told ADAPT you're moving without one. If that changes, try it in What if? to see how your plan would change.",
        citations: [],
        links: [{ to: "/simulate", label: "Try it in What if?" }],
      };
    }
    const threshold = income?.properties.threshold_aed;
    const withHousing = income?.properties.threshold_with_accommodation_aed;
    return {
      tools: [
        { name: "get_journey_node", label: "Checking your spouse's visa", args: { key: "family.spouse_visa" }, result: visa.status },
        { name: "search_governance", label: "Looking up the official rules", args: { query: "family residence visa" }, result: "3 related rules" },
      ],
      text:
        `To sponsor your spouse you'll need your own residence visa first, and your marriage certificate attested at home and then by UAE MoFA. Have proof of address ready too, and check ICP's current document list.` +
        (threshold ? ` There's also a minimum monthly income: AED ${threshold}, or AED ${withHousing} if accommodation is provided. Confirm the current figures on the official page.` : "") +
        `\n\nRight now this step is ${visa.status === "blocked" ? "blocked" : "ready"}.` +
        (visa.blockers.length ? ` It's waiting on:\n${visa.blockers.map((b) => `• ${b.message}`).join("\n")}` : ""),
      citations: [...citationsFrom(visa.evidence), ...citationsFrom(income?.evidence)].slice(0, 3),
      links: [{ to: `/journey?node=${visa.key}`, label: "Open in your journey" }],
    };
  }

  if (has(q, "mainland", "adgm", "free zone", "freezone", "jurisdiction")) {
    const mainland = governanceNode("location.abu_dhabi_mainland");
    const adgm = governanceNode("location.adgm");
    return {
      tools: [{ name: "search_governance", label: "Comparing mainland and ADGM", args: { query: "mainland adgm" }, result: "2 jurisdictions" }],
      text: `Mainland companies are licensed by ADDED and can trade across the emirate; the route is trade name, initial approval, premises, then your licence. ADGM is a free zone with its own registration authority, where you incorporate through the ADGM online registry.\n\nEither licence leads to the same establishment card, so your residency steps stay the same. What if? shows exactly which steps change.`,
      citations: [...citationsFrom(mainland?.evidence), ...citationsFrom(adgm?.evidence)],
      links: [{ to: "/simulate", label: "Compare in What if?" }],
    };
  }

  if (has(q, "medical", "book", "appointment", "biometric")) {
    const key = has(q, "biometric", "emirates id") ? "residency.biometrics" : "residency.medical";
    const node = nodeByKey(journey, key)!;
    if (node.status === "blocked") {
      return {
        tools: [{ name: "get_journey_node", label: `Checking ${node.title.toLowerCase()}`, args: { key }, result: "Blocked" }],
        text: `${node.title} can't be booked yet. ${node.blockers.map((b) => b.message).join(" ")} I'll prepare the booking as soon as it's unblocked.`,
        citations: citationsFrom(node.evidence),
        links: [{ to: `/journey?node=${key}`, label: "See what it's waiting for" }],
      };
    }
    return {
      tools: [
        { name: "get_journey_node", label: `Checking ${node.title.toLowerCase()}`, args: { key }, result: "Ready to book" },
        { name: "prepare_action", label: "Preparing the booking", args: { key }, result: "Needs your approval" },
      ],
      text: `I've prepared the booking details for your ${node.title.toLowerCase()}. Review what will be shared and approve it; you'll pick the slot yourself on the official page.`,
      citations: citationsFrom(node.evidence),
      approvalNodeKey: key,
      links: [],
    };
  }

  if (has(q, "document", "passport", "upload", "attest", "certificate")) {
    const docs = [...store.documents.values()];
    const missing = journey.nodes.filter((n) => n.kind === "document" && n.status === "waiting_for_me");
    const review = docs.filter((d) => d.status === "needs_review");
    return {
      tools: [{ name: "list_documents", label: "Checking your documents", args: {}, result: `${docs.length} on file` }],
      text:
        `You have ${docs.length} ${docs.length === 1 ? "document" : "documents"} on file.` +
        (review.length ? ` ${review.length} ${review.length === 1 ? "needs" : "need"} your review before ADAPT uses ${review.length === 1 ? "it" : "them"}.` : "") +
        (missing.length ? `\n\nStill needed:\n${list(missing)}` : "\n\nNothing else is missing right now."),
      citations: missing.flatMap((n) => citationsFrom(n.evidence)).slice(0, 2),
      links: [{ to: "/documents", label: "Open Documents" }],
    };
  }

  if (has(q, "communit", "friend", "event", "meet", "people", "church", "mosque", "temple", "worship")) {
    const items = [...store.discoverItems.values()].slice(0, 3);
    return {
      tools: [{ name: "get_discover", label: "Checking community research", args: {}, result: `${store.discoverItems.size} results` }],
      text: items.length
        ? `A few places to start:\n${items.map((i) => `• ${i.title}: ${i.summary}`).join("\n")}\n\nThese come from the web, not from government sources, so check each source before relying on it.`
        : "Community research is still running in the background. I'll let you know when your Abu Dhabi Life Brief is ready.",
      citations: items
        .filter((i) => i.source.url)
        .map((i) => ({ title: i.source.title, url: i.source.url!, authority: null, retrievedAt: i.lastCheckedAt, section: null, quote: null, kind: i.evidenceKind })),
      links: [{ to: "/discover", label: "Open Discover" }],
    };
  }

  if (has(q, "tawtheeq", "lease", "rent", "housing", "home", "apartment")) {
    const node = nodeByKey(journey, "housing.tawtheeq")!;
    return {
      tools: [{ name: "get_journey_node", label: "Checking your housing steps", args: { key: node.key }, result: node.status }],
      text: "Once you sign a long-term lease, register it with Tawtheeq on TAMM. The registered lease becomes your proof of address for utilities and many services. Short stays in hotels or serviced apartments usually can't be registered.",
      citations: citationsFrom(node.evidence),
      links: [{ to: `/journey?node=${node.key}`, label: "Open in your journey" }],
    };
  }

  if (has(q, "tax", "corporate")) {
    const gov = governanceNode("service.corporate_tax_registration");
    return {
      tools: [{ name: "search_governance", label: "Looking up corporate tax", args: { query: "corporate tax" }, result: "1 service" }],
      text: "UAE companies register for corporate tax with the Federal Tax Authority on EmaraTax, once the company is licensed. You sign in with UAE PASS; ADAPT hands you to the official page and never asks for your login.",
      citations: citationsFrom(gov?.evidence),
      links: [],
    };
  }

  if (has(q, "block", "stuck", "waiting", "why")) {
    const blocked = blockedNodes(journey).slice(0, 4);
    return {
      tools: [{ name: "get_blockers", label: "Checking what's blocked", args: {}, result: `${blocked.length} blocked` }],
      text: blocked.length ? `These steps are waiting on something:\n${list(blocked)}` : "Nothing is blocked right now.",
      citations: [],
      links: [{ to: "/journey?filter=blocked", label: "See blocked steps" }],
    };
  }

  if (has(q, "next", "today", "do now", "start", "status", "progress", "what should")) {
    const next = nextActions(journey, 3);
    const { percent } = completion(journey);
    return {
      tools: [{ name: "get_journey_status", label: "Checking your journey", args: {}, result: `${percent}% complete` }],
      text: `You're ${percent}% of the way through your plan. The longest chain of remaining steps is about ${criticalPathDays(journey)} days (ADAPT's estimate).\n\nMost useful next:\n${next.map((n) => `• ${n.title}: ${n.action?.label ?? "open it"}`).join("\n")}`,
      citations: citationsFrom(next[0]?.evidence),
      links: next[0] ? [{ to: `/journey?node=${next[0].key}`, label: `Open "${next[0].title}"` }] : [],
    };
  }

  const matches = searchGovernance(text, 2);
  if (matches.length) {
    return {
      tools: [{ name: "search_governance", label: "Searching Abu Dhabi's services", args: { query: text }, result: `${matches.length} matches` }],
      text: matches.map((m) => `${m.label}: ${m.summary ?? ""}`).join("\n\n") + "\n\nConfirm current details on the official page.",
      citations: matches.flatMap((m) => citationsFrom(m.evidence)).slice(0, 3),
      links: [{ to: "/knowledge/governance", label: "Explore the governance graph" }],
    };
  }

  return {
    tools: [{ name: "search_governance", label: "Searching Abu Dhabi's services", args: { query: text }, result: "No matches" }],
    text: "I couldn't find that in ADAPT's knowledge yet. I can help with your next steps, company setup, residency, your spouse's visa, housing, documents or communities.",
    citations: [],
    links: [],
  };
}

export async function* mockRespond(text: string, context: AssistantContext, signal?: AbortSignal): AsyncGenerator<AssistantEvent> {
  const turnId = uid("turn");
  yield { type: "state", state: "thinking" };
  yield { type: "turn_started", turnId };
  const journey = store.journey();
  const response = plan(text, journey);

  for (const t of response.tools) {
    const call: ToolCall = { id: uid("call"), name: t.name, label: t.label, args: t.args, status: "running", resultSummary: null };
    yield { type: "tool_call", turnId, call };
    await delay(550 + Math.random() * 350, signal);
    yield { type: "tool_result", turnId, callId: call.id, summary: t.result, ok: true };
  }

  if (context.channel === "voice") yield { type: "state", state: "speaking" };
  const words = response.text.split(/(\s+)/);
  for (let i = 0; i < words.length; i += 3) {
    await delay(28, signal);
    yield { type: "text_delta", turnId, text: words.slice(i, i + 3).join("") };
  }
  for (const citation of response.citations) yield { type: "citation", turnId, citation };

  if (response.approvalNodeKey) {
    const approval = store.createApproval(response.approvalNodeKey, null);
    if (approval) yield { type: "approval", turnId, approval: { ...approval } };
  }
  for (const link of response.links) yield { type: "navigate", turnId, to: link.to, label: link.label };
  yield { type: "turn_completed", turnId };
  yield { type: "state", state: context.channel === "voice" ? "listening" : "idle" };
}
