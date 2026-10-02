import { tr, localize, useLocale } from "@/i18n";
import { LanguagePicker } from "@/i18n/LanguageSelector";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { Check, ChevronLeft, ChevronRight, ExternalLink, FileText, Mic, RotateCcw, Volume2 } from "lucide-react";
import { useSearchParams } from "react-router";
import { BrandMark } from "@/app/layout/BrandMark";
import { Button } from "@/components/ui/Button";
import { ProgressBar } from "@/components/ui/Progress";
import { useDictation } from "@/features/onboarding/useDictation";
import { config } from "@/lib/config";
import { cn } from "@/lib/cn";
import { DEMO_STORAGE_KEY, INTRO_REPLY, SCENES, adapterActions, agentStages, blockers, branchChanges, initialProgress, readProgress, replay, researchProgress, scriptedAnswer, writeProgress } from "./replay";
import "./hero.css";

function storage() { try { return window.localStorage; } catch { return null; } }
function Card({ title, children, className }: { title?: string; children: ReactNode; className?: string }) {
  useLocale();
  return <section className={cn("hero-card", className)}>{title && <h2>{localize(title)}</h2>}{localize(children)}</section>;
}
function Source({ url, title }: { url: string; title: string }) {
  useLocale();
  return <a className="hero-source" href={url} target="_blank" rel="noopener noreferrer">{localize(title)}<ExternalLink className="size-3.5 shrink-0" aria-hidden /><span className="sr-only"> {tr("copy.opens_in_a_new_tab_bf5b990")}</span></a>;
}

type GraphNode = { key: string; label: string; removed?: boolean };
function Graph({ nodes, edges, label, active = false }: { nodes: GraphNode[]; edges: { source: string; target: string }[]; label: string; active?: boolean }) {
  useLocale();
  const positions = new Map(nodes.map((n, i) => [n.key, { x: 36 + (i % 3) * 320, y: 28 + Math.floor(i / 3) * 120 }]));
  const height = Math.ceil(nodes.length / 3) * 120 + 12;
  return <div className="hero-graph" role="img" aria-label={localize(label)}>
    <svg viewBox={`0 0 1000 ${height}`} aria-hidden>
      <defs><marker id={`arrow-${label.replace(/\W/g, "")}`} markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto"><path d="M0,0 L6,3 L0,6" className="hero-arrow" /></marker></defs>
      {edges.map((e, i) => { const a = positions.get(e.source), b = positions.get(e.target); if (!a || !b) return null; const removed = nodes.some((n) => (n.key === e.source || n.key === e.target) && n.removed); return <path key={i} d={`M${a.x + 136},${a.y + 38} C${a.x + 136},${a.y + 110} ${b.x + 136},${b.y - 34} ${b.x + 136},${b.y + 8}`} markerEnd={`url(#arrow-${label.replace(/\W/g, "")})`} className={cn("hero-edge", active && "hero-flow", removed && "hero-edge-removed")} />; })}
      {nodes.map((n, i) => { const p = positions.get(n.key)!; const words = n.label.length > 35 ? [n.label.slice(0, n.label.lastIndexOf(" ", 35)), n.label.slice(n.label.lastIndexOf(" ", 35) + 1)] : [n.label]; return <g key={n.key} className={cn("hero-node", n.removed && "hero-node-removed")}>
        <rect x={p.x} y={p.y} width="274" height="76" rx="13" />
        <circle cx={p.x + 23} cy={p.y + 37} r="5" />
        {words.slice(0, 2).map((line, j) => <text key={j} x={p.x + 38} y={p.y + (words.length > 1 ? 32 : 43) + j * 19}>{line.length > 37 ? `${line.slice(0, 36)}…` : line}</text>)}
        <text x={p.x + 250} y={p.y + 19} className="hero-node-number">{localize(i + 1)}</text>
      </g>; })}
    </svg>
    <p className="hero-graph-caption">{localize(label)}</p>
  </div>;
}

const planKeys = ["appointment.uae_mission_visit", "service.uae_mission_attestation", "service.mofa_attestation", "service.residence_visa_investor", "service.emirates_id", "service.tawtheeq", tr("copy.service_family_entry_permit_spouse_38f6b6e", { lng: "en" }), tr("copy.requirement_family_accommodation_spouse_1d78e19", { lng: "en" }), tr("copy.service_family_residence_visa_spouse_80e319f", { lng: "en" })];
function PlanGraph({ alone = false }: { alone?: boolean }) {
  useLocale();
  const removed = new Set(branchChanges().removedTasks.map((t) => t.key));
  const nodes = planKeys.map((key) => ({ key, label: replay.tasks.find((t) => t.key === key)?.title ?? key, removed: alone && removed.has(key) }));
  return <Graph nodes={nodes} edges={replay.dependencies.map((d) => ({ source: d.depends_on, target: d.task }))} label={alone ? tr("copy.move_alone_first_dashed_steps_move_to_your_wife__e1dc601") : tr("copy.family_settlement_dependencies_a_focused_view_of_6a3f531")} active />;
}

const titles = [tr("copy.your_next_chapter_starts_here_6f745f5", { lng: "en" }), tr("copy.two_documents_a_clearer_picture_2791248", { lng: "en" }), tr("copy.your_user_digital_twin_dcbd1ba", { lng: "en" }), tr("copy.the_rules_behind_your_plan_7332a46", { lng: "en" }), tr("copy.start_your_langgraph_journey_ffc3a5b", { lng: "en" }), tr("copy.every_requirement_has_a_reason_09e852a", { lng: "en" }), tr("copy.prepared_for_your_approval_89102b1", { lng: "en" }), tr("copy.life_beyond_the_paperwork_ef87bf0", { lng: "en" }), tr("copy.what_if_you_move_alone_first_198154f", { lng: "en" }), tr("copy.your_abu_dhabi_plan_522dbdd", { lng: "en" })];

export default function HeroDemoPage() {
  useLocale();
  const [params, setParams] = useSearchParams();
  const [progress, setProgress] = useState(() => { const p = readProgress(storage()); const requested = Number(params.get("scene")); return params.has("scene") && Number.isInteger(requested) && requested >= 0 && requested < SCENES.length ? { ...p, scene: requested } : p; });
  const [now, setNow] = useState(Date.now);
  const [docStarted, setDocStarted] = useState<number | null>(null);
  const [previewUnavailable, setPreviewUnavailable] = useState(false);
  const [reply, setReply] = useState("");
  const [audioNote, setAudioNote] = useState("");
  const [question, setQuestion] = useState<"first" | "blockers" | "connect">("first");
  const alive = useRef(true);
  const speechEpoch = useRef(0);
  const loadController = useRef<AbortController | null>(null);
  const completeIntro = () => { setProgress((p) => ({ ...p, intro: true })); speak(INTRO_REPLY); };
  const dictation = useDictation((text) => {
    // Raw microphone text is neither rendered nor stored in the synthetic sandbox.
    // Only the known stage prompt or one of the predefined questions is accepted.
    if (progress.scene === 0) {
      if (/founder/i.test(text) && /Abu Dhabi/i.test(text)) completeIntro();
      else setAudioNote(tr("copy.say_the_demo_opening_or_choose_use_scripted_open_c0cf367"));
    } else {
      const topic = /block|hold|income/i.test(text) ? "blockers" : /community|connect|network/i.test(text) ? "connect" : "first";
      speak(scriptedAnswer(topic));
    }
  });

  function speak(text: string) {
    dictation.reset();
    const epoch = ++speechEpoch.current;
    setReply(text);
    setAudioNote("");
    if (!("speechSynthesis" in window)) { setAudioNote(tr("copy.audio_unavailable_the_complete_response_is_shown_8dc83ec")); return; }
    try {
      window.speechSynthesis.cancel();
      const utterance = new SpeechSynthesisUtterance(text);
      utterance.lang = "en-US"; utterance.rate = 1;
      const voices = window.speechSynthesis.getVoices();
      utterance.voice = voices.find((v) => v.lang.startsWith("en") && /natural|online|samantha|aria/i.test(v.name)) ?? voices.find((v) => v.lang.startsWith("en")) ?? null;
      utterance.onerror = () => { if (alive.current && epoch === speechEpoch.current) setAudioNote(tr("copy.audio_stopped_you_can_read_the_response_or_try_v_6ff80fe")); };
      window.speechSynthesis.speak(utterance);
    } catch { setAudioNote(tr("copy.audio_unavailable_the_complete_response_is_shown_8dc83ec")); }
  }

  useEffect(() => { writeProgress(storage(), progress); }, [progress]);
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 250);
    // Warm the speech voice list without waiting for a network integration.
    try { window.speechSynthesis?.getVoices(); } catch { /* text remains available */ }
    alive.current = true;
    return () => { alive.current = false; clearInterval(id); loadController.current?.abort(); window.speechSynthesis?.cancel(); };
  }, []);
  useEffect(() => {
    if (docStarted !== null && now - docStarted >= 2400) { setProgress((p) => ({ ...p, documents: true })); setDocStarted(null); }
  }, [now, docStarted]);
  useEffect(() => { const s = Number(params.get("scene")); if (params.has("scene") && Number.isInteger(s) && s >= 0 && s < SCENES.length) setProgress((p) => p.scene === s ? p : { ...p, scene: s }); }, [params]);
  useEffect(() => { document.title = `${SCENES[progress.scene]} · ADAPT demo`; }, [progress.scene]);

  function go(scene: number) {
    dictation.reset();
    setProgress((p) => ({ ...p, scene }));
    setParams({ scene: String(scene) });
    window.scrollTo({ top: 0, behavior: "instant" });
  }
  function reset() {
    dictation.reset(); speechEpoch.current++; loadController.current?.abort(); window.speechSynthesis?.cancel();
    try { storage()?.removeItem(DEMO_STORAGE_KEY); } catch { /* disabled storage */ }
    setProgress(initialProgress()); setDocStarted(null); setPreviewUnavailable(false); setReply(""); setAudioNote(""); setQuestion("first");
    setParams({}, { replace: true }); window.scrollTo(0, 0);
  }
  async function uploadSpecimens() {
    if (docStarted !== null) return;
    setDocStarted(Date.now()); setPreviewUnavailable(false);
    loadController.current?.abort();
    const controller = new AbortController(); loadController.current = controller;
    // Only public bundled specimens can enter this presentation. No arbitrary file picker.
    try {
      const outcomes = await Promise.all(replay.documents.slice(0, 2).map(async (doc) => {
        const response = await fetch(doc.url, { signal: AbortSignal.any([controller.signal, AbortSignal.timeout(2500)]), cache: "force-cache" });
        if (!response.ok) throw new Error(tr("copy.specimen_preview_unavailable_f2cb363"));
        const bytes = await response.arrayBuffer();
        const digest = Array.from(new Uint8Array(await crypto.subtle.digest(tr("copy.sha_256_45792d6"), bytes)), (b) => b.toString(16).padStart(2, "0")).join("");
        if (digest !== doc.sha256) throw new Error(tr("copy.specimen_checksum_mismatch_f2080e0"));
      }));
      void outcomes;
    } catch { if (!controller.signal.aborted && alive.current) setPreviewUnavailable(true); }
  }

  const research = researchProgress(progress.researchStartedAt, now);
  const elapsedStages = progress.agentStartedAt === null ? 0 : Math.min(agentStages.length, Math.max(0, Math.floor((now - progress.agentStartedAt) / 500)));
  const approvalGate = agentStages.findIndex((event) => event.node === "human_approval");
  const agents = progress.decision === "approved" ? elapsedStages : Math.min(elapsedStages, approvalGate);
  const docStages = progress.documents ? 4 : docStarted === null ? 0 : Math.min(4, 1 + Math.floor((now - docStarted) / 600));
  const scene = progress.scene;
  const changes = branchChanges();
  const unknownRule = replay.governance.nodes.find((n) => n.key === "eligibility_rule.family_sponsor_income")!;
  const family = replay.tasks.find((t) => t.key === "service.family_residence_visa@spouse")!;
  const draft = replay.drafts[0]!;
  const action = replay.featuredAction;

  return <div className="hero-demo"><div className="px-4 pt-3 lg:absolute lg:end-4 lg:top-0 lg:z-20"><LanguagePicker /></div>
    <aside className="hero-sidebar">
      <a href="/demo/founder-arrival" className="hero-brand"><BrandMark className="size-9" /><span>{tr("copy.adapt_2e26648")}<small>{tr("copy.abu_dhabi_made_personal_34a7a44")}</small></span></a>
      <nav aria-label={tr("copy.demo_chapters_6f4cdda")}>{SCENES.map((title, i) => <button key={title} onClick={() => go(i)} aria-current={scene === i ? "step" : undefined}><span>{i + 1 < scene + 1 ? <Check className="size-3.5" /> : String(i + 1).padStart(2, "0")}</span>{localize(title)}</button>)}</nav>
      <p className="hero-sidebar-note">{tr("copy.synthetic_persona_b0cacc3")}<br />{tr("copy.recorded_langgraph_run_a777380")}<br />{tr("copy.official_handoffs_only_ba22b49")}</p>
    </aside>
    <div className="hero-workspace">
      <header className="hero-topbar"><span className="hero-demo-badge">{tr("copy.demo_specimen_data_7f910b0")}</span><span className="hero-research-state" role="status">{progress.researchStartedAt === null ? tr("copy.research_ready_to_start_80e8d90") : research < 1 ? tr("copy.research_running_v0_3bd212a", { v0: Math.round(research * 100) }) : tr("copy.research_complete_5_topics_d4eaacb")}</span>{config.demoMode && <Button variant="ghost" icon={<RotateCcw className="size-4" />} onClick={reset}>{tr("copy.demo_reset_7985161")}</Button>}</header>
      <main className={cn("hero-main", scene === 9 && "hero-final")} id="main">
        <div className="hero-heading"><p className="hero-eyebrow">{localize(String(scene + 1).padStart(2, "0"))} {tr("copy.10_arrive_settle_connect_build_20671bf")}</p><h1>{localize(titles[scene])}</h1><p className="hero-subtitle">{scene === 9 ? tr("copy.one_connected_plan_for_kabir_and_ayesha_s_move_440ce29") : tr("copy.kabir_and_ayesha_rahman_fictional_household_no_r_4ee1189")}</p></div>

        {scene === 0 && <div className="hero-grid"><Card className="hero-intro"><span className="hero-kicker">{tr("copy.tell_adapt_about_your_move_0c0d117")}</span><blockquote>{tr("copy.text_54a985b")}{localize(replay.prompt)}{tr("copy.text_095a6ce")}</blockquote><div className="hero-buttons"><Button icon={<Mic className="size-4" />} disabled={!dictation.supported} onClick={dictation.listening ? dictation.stop : dictation.start}>{dictation.listening ? tr("copy.stop_listening_e134211") : tr("copy.speak_the_opening_584860c")}</Button><Button variant="secondary" onClick={completeIntro}>{tr("copy.use_scripted_opening_09802e9")}</Button></div><p className="hero-caption">{tr("copy.browser_dictation_spoken_scripted_response_only__134d90f")}</p></Card><Card title={tr("copy.extracted_intent_6d9a91b")}>{progress.intro ? <dl className="hero-facts">{[[tr("copy.who_7d53161"), tr("copy.indian_technology_founder_97f1c14")], [tr("copy.when_769bb19"), tr("copy.next_month_8abf7cf")], [tr("copy.household_52996fa"), tr("copy.moving_with_wife_3c9f62e")], [tr("copy.goals_48d8c62"), tr("copy.establish_company_find_housing_settle_family_6640c68")]].map(([label, value]) => <div key={label}><dt>{localize(label)}</dt><dd><span>{localize(value)}</span><span className="hero-pill">{tr("copy.stated_763f230")}</span></dd></div>)}</dl> : <p className="hero-muted">{tr("copy.speak_the_opening_or_load_the_script_to_reveal_t_d4036b5")}</p>}<p className="hero-caption">{tr("copy.company_jurisdiction_and_faith_are_separate_expl_b91ba3a")}</p></Card></div>}

        {scene === 1 && <><div className="hero-buttons"><Button icon={<FileText className="size-4" />} loading={docStarted !== null} disabled={progress.documents} onClick={() => void uploadSpecimens()}>{progress.documents ? tr("copy.specimens_loaded_38033ed") : tr("copy.upload_demo_documents_9076956")}</Button><span className="hero-caption">{tr("copy.passport_marriage_certificate_bundled_synthetic__585c6fe")}</span></div>{previewUnavailable && <p className="hero-recovery" role="status">{tr("copy.document_preview_unavailable_continuing_with_the_d424859")}</p>}<ol className="hero-pipeline" aria-label={tr("copy.document_extraction_stages_996c99c")}>{[tr("copy.document_uploaded_2c6594a"), tr("copy.document_analyzed_6f947b6"), tr("copy.facts_extracted_67a77ce"), tr("copy.user_graph_updated_9155c8c")].map((label, i) => <li className={i < docStages ? "is-complete" : ""} key={label}><span>{i < docStages ? <Check className="size-4" /> : i + 1}</span>{localize(label)}</li>)}</ol><div className="hero-grid">{replay.documents.slice(0, 2).map((doc) => <Card title={localize(doc.title)} key={doc.key}><div className="hero-specimen">{tr("copy.specimen_4501e07")}<small>{localize(doc.filename)}</small><p>{tr("copy.synthetic_demo_document_fictional_details_only_f101a0a")}</p></div>{docStages >= 3 && <dl className="hero-facts">{doc.fields.slice(0, 5).map((field) => <div key={field.name}><dt>{localize(field.name.replaceAll("_", " "))}</dt><dd><span>{localize(String(field.value))}</span><span className="hero-pill">{localize(Math.round(field.confidence * 100))}{tr("copy.text_4345cb1")}</span></dd></div>)}</dl>}<p className="hero-caption">{tr("copy.recorded_local_pdf_text_extraction_20f8024")}{doc.key === "passport" && tr("copy.verified_mrz_check_digits_7c19421")}{tr("copy.vision_is_optional_for_these_specimens_16bdee0")}</p>{!previewUnavailable && <Source url={doc.url} title={tr("copy.open_synthetic_pdf_8097865")} />}</Card>)}</div></>}

        {scene === 2 && <><Card><Graph nodes={[{ key: "self", label: "Kabir Rahman · technology founder" }, { key: "passport", label: "Indian nationality · passport" }, { key: "company", label: "Noorvia Labs · ADGM plan" }, { key: "spouse", label: "Ayesha Rahman · spouse" }, { key: "home", label: "Housing · Abu Dhabi" }, { key: "goals", label: "Company · residency · family" }]} edges={["passport", "company", "spouse", "home", "goals"].map((target) => ({ source: "self", target }))} label={tr("copy.synthetic_user_digital_twin_facts_documents_hous_df57a03")} active /></Card><p className="hero-caption">{tr("copy.passport_and_marriage_fields_come_from_the_recor_77ec88f")}</p></>}

        {scene === 3 && <><Card><Graph nodes={["service.family_residence_visa", "eligibility_rule.family_sponsor_income", "requirement.family_accommodation", "document.marriage_certificate_attested", "service.mofa_attestation", "authority.icp"].map((key) => ({ key, label: replay.governance.nodes.find((n) => n.key === key)!.label }))} edges={replay.governance.edges.map((e) => ({ source: e.source, target: e.target }))} label={tr("copy.governance_graph_official_services_requirements__b5e54f7")} active /></Card><p className="hero-caption">{tr("copy.public_governance_seed_with_linked_official_page_3489b16")}</p><Source url={family.official_url!} title={tr("copy.family_residence_service_icp_48bde2a")} /></>}

        {scene === 4 && <><div className="hero-buttons"><Button disabled={progress.agentStartedAt !== null} onClick={() => setProgress((p) => ({ ...p, agentStartedAt: Date.now() }))}>{progress.agentStartedAt === null ? tr("copy.start_langgraph_journey_e92e3ea") : tr("copy.recorded_journey_running_e818720")}</Button><span className="hero-caption">{tr("copy.replay_of_actual_node_events_from_the_real_compi_968bcd4")}</span></div><Card><ol className="hero-agents" aria-label={tr("copy.langgraph_agent_flow_f095e2d")}>{agentStages.map((event, i) => <li key={event.node} className={cn(i < agents && "is-complete", i === agents && progress.agentStartedAt !== null && "is-running")}><span>{i < agents ? <Check className="size-4" /> : i + 1}</span><strong>{localize(event.label)}</strong><small>{localize(event.node?.replaceAll("_", " "))}</small></li>)}</ol></Card>{agents >= 9 && <div className="hero-stats" aria-live="polite"><Card><strong>{localize(adapterActions.length)} {tr("copy.actions_identified_da97790")}</strong><p>{localize(replay.tasks.length)} {tr("copy.total_steps_including_supporting_steps_aaf31c6")}</p></Card><Card><strong>{localize(blockers.length)} {tr("copy.blockers_fa80990")}</strong><p>{tr("copy.missing_eligibility_facts_dependencies_remain_vi_aa15329")}</p></Card><Card><strong>{progress.decision === "pending" ? 1 : 0} {tr("copy.approval_required_2569b54")}</strong><p>{tr("copy.for_the_featured_appointment_one_additional_deci_41747f7")}</p></Card></div>}</>}

        {scene === 5 && <div className="hero-grid"><Card title={tr("copy.sponsor_your_wife_s_residence_b8b318b")}><dl className="hero-requirement"><div><dt>{tr("copy.user_fact_9c01f7f")}</dt><dd>{tr("copy.moving_with_ayesha_his_spouse_monthly_income_and_8c7d4d5")}</dd></div><div><dt>{tr("copy.governance_rule_9ce5022")}</dt><dd>{localize(unknownRule.label)}<p>{localize(unknownRule.summary)}</p></dd></div><div><dt>{tr("copy.evidence_7ea014d")}</dt><dd><span className="hero-pill">{tr("copy.official_reference_governance_seed_5062bc2")}</span><Source url={unknownRule.official_url ?? family.official_url!} title={tr("copy.check_the_cited_official_requirement_bf2aa79")} /></dd></div><div><dt>{tr("copy.next_action_d816c3c")}</dt><dd>{tr("copy.confirm_monthly_income_and_accommodation_then_re_b4b51e8")}</dd></div></dl></Card><Card title={tr("copy.why_it_waits_3786920")}><PlanGraph /><p className="hero-caption">{tr("copy.your_residency_emirates_id_housing_and_marriage__c9e73dc")}</p></Card></div>}

        {scene === 6 && <div className="hero-grid"><Card title={tr("copy.draft_documentation_ba149c2")}><span className="hero-pill">{tr("copy.draft_review_before_use_e670caf")}</span><h3>{localize(draft.title)}</h3><pre className="hero-draft">{localize(draft.body_markdown)}</pre><p className="hero-caption">{tr("copy.a_real_template_draft_from_the_recorded_journey__6bece64")}</p></Card><Card title={tr("copy.appointment_action_adapter_6365d6d")}><span className="hero-pill">{tr("copy.demo_adapter_example_availability_13aeceb")}</span><h3>{localize(action.title)}</h3><p>{tr("copy.marriage_certificate_attestation_uae_mission_in__537dfd5")}</p><ul className="hero-list">{action.response_metadata.demo_response.example_slots.map((slot) => <li key={slot.starts_at}>{localize(slot.label)}</li>)}</ul><p className="hero-caption">{tr("copy.example_slots_from_the_recorded_run_no_current_a_8aad9e1")}</p><div className="hero-buttons">{progress.decision === "pending" ? <><Button onClick={() => setProgress((p) => ({ ...p, decision: "approved" }))}>{tr("copy.approve_handoff_7876827")}</Button><Button variant="secondary" onClick={() => setProgress((p) => ({ ...p, decision: "rejected" }))}>{tr("copy.keep_for_later_a212630")}</Button></> : <span className="hero-pill">{progress.decision === "approved" ? tr("copy.action_prepared_for_official_handoff_c58961b") : tr("copy.deferred_nothing_sent_5bf1cc2")}</span>}</div>{progress.decision === "approved" && <><Source url={action.official_url!} title={tr("copy.continue_on_the_official_mofa_site_9605b19")} /><p className="hero-caption">{tr("copy.you_finish_on_the_official_site_adapt_has_not_bo_1845418")}</p></>}</Card></div>}

        {scene === 7 && <><div className="hero-buttons"><Button disabled={progress.researchStartedAt !== null} onClick={() => setProgress((p) => ({ ...p, researchStartedAt: Date.now() }))}>{tr("copy.start_background_research_fe10d6f")}</Button><span className="hero-caption">{tr("copy.dated_reviewed_source_list_works_without_live_we_8ee8960")}</span></div>{progress.researchStartedAt !== null && <ProgressBar value={research} label={research < 1 ? tr("copy.research_continues_while_you_talk_bd81e93") : tr("copy.research_complete_5_topics_d4eaacb")} />}<div className="hero-research-grid">{replay.research.map((group, i) => <Card title={localize(group.title)} key={group.key}><span className="hero-pill">{research >= (i + 1) / 5 ? tr("copy.ready_20c7c55") : progress.researchStartedAt ? tr("copy.working_3b4dfc9") : tr("copy.queued_6a59987")}</span>{research >= (i + 1) / 5 ? group.entries.slice(0, 2).map((entry) => <div className="hero-result" key={entry.key}><h3>{localize(entry.title)}</h3><Source url={entry.url} title={localize(entry.source_title)} /><p className="hero-caption">{tr("copy.reviewed_source_list_checked_ee8fdd9")}{localize(entry.retrieved_at.slice(0, 10))} {tr("copy.check_current_details_on_the_source_f9ae31d")}</p></div>) : <p className="hero-muted">{localize(group.description)}</p>}</Card>)}</div><Card title={tr("copy.things_you_may_not_have_considered_6ad47cd")}><ul className="hero-list">{replay.considerations.map((c) => <li key={c.id}><strong>{localize(c.title)}</strong><p>{localize(c.detail)}</p></li>)}</ul><Source url={replay.tasks.find((t) => t.key === "service.mofa_attestation")!.official_url!} title={tr("copy.marriage_attestation_official_reference_f44130f")} /><Source url={replay.tasks.find((t) => t.key === "service.tawtheeq")!.official_url!} title={tr("copy.tawtheeq_official_reference_411d4cc")} /></Card></>}

        {scene === 8 && <><div className="hero-buttons"><Button aria-pressed={progress.alone} onClick={() => setProgress((p) => ({ ...p, alone: !p.alone }))}>{progress.alone ? tr("copy.restore_family_arrival_9232925") : tr("copy.move_alone_first_234184e")}</Button><span className="hero-caption">{tr("copy.branch_comparison_from_a_second_real_graph_run_y_ee0505a")}</span></div><Card><PlanGraph alone={progress.alone} /></Card>{progress.alone && <div className="hero-stats"><Card><strong>{localize(changes.removedTasks.length)} {tr("copy.steps_move_to_later_52cea96")}</strong><p>{tr("copy.ayesha_s_documents_attestation_and_family_reside_8deaf55")}</p></Card><Card><strong>{localize(changes.removedDependencies.length)} {tr("copy.dependencies_change_a77eb69")}</strong><p>{tr("copy.dashed_connections_leave_your_first_arrival_296f90f")}</p></Card><Card><strong>{tr("copy.family_plan_preserved_50d10fd")}</strong><p>{tr("copy.return_to_the_final_plan_with_one_click_14faa99")}</p></Card></div>}<Button variant="secondary" onClick={() => go(9)}>{tr("copy.return_to_final_plan_338b3ca")}</Button></>}

        {scene === 9 && <><div className="hero-final-grid">{[{ title: tr("copy.arrive_342a857"), subtitle: tr("copy.a_clear_route_to_residency_df9f449"), areas: ["residency", "health"] }, { title: tr("copy.settle_3ebe66c"), subtitle: tr("copy.a_home_and_a_family_plan_9030e62"), areas: ["housing", "family"] }, { title: tr("copy.connect_b65463c"), subtitle: tr("copy.people_culture_and_community_d4a333e"), areas: [] }, { title: tr("copy.build_bbd80cf"), subtitle: tr("copy.turn_your_company_plan_into_action_e7c9314"), areas: ["business"] }].map((pillar) => <Card title={localize(pillar.title)} key={pillar.title}><p className="hero-muted">{localize(pillar.subtitle)}</p><ul className="hero-list">{pillar.title === "Connect" ? [tr("copy.indian_community_31a6818"), tr("copy.faith_community_explicit_opt_in_620d607"), tr("copy.professional_network_696df2f"), tr("copy.cultural_guide_4c364a8"), tr("copy.starter_kit_140c54d")].map((label) => <li key={label}>{localize(label)}</li>) : replay.tasks.filter((t) => pillar.areas.includes(t.area)).slice(0, 4).map((t) => <li key={t.key}>{localize(t.title)}<small>{t.status === "ready" ? tr("copy.next_action_d816c3c") : tr("copy.waiting_on_prerequisites_7ae05d9")}</small></li>)}</ul></Card>)}</div><div className="hero-grid"><Card title={tr("copy.next_actions_blockers_173854d")}><p>{localize(adapterActions.length)} {tr("copy.adapter_actions_573958c")}{localize(replay.tasks.length)} {tr("copy.total_steps_a6cd4bf")}</p><ul className="hero-list">{blockers.map((b) => <li key={b.id}><strong>{localize(b.title.replace("Missing information: ", ""))}</strong><p>{localize(b.resolution ?? b.detail)}</p></li>)}</ul><p className="hero-caption">{tr("copy.additional_document_requirements_and_dependency__174c312")}</p><Button variant="secondary" onClick={() => go(5)}>{tr("copy.open_a_requirement_9bde636")}</Button></Card><Card title={tr("copy.documents_research_441bbd8")}><p>{tr("copy.passport_marriage_certificate_business_profile_a7ca80d")}</p><span className="hero-pill">{progress.documents ? tr("copy.synthetic_extraction_replay_loaded_d7bef3e") : tr("copy.specimens_ready_to_load_56e3954")}</span><p className="mt-4">{tr("copy.draft_sponsorship_letter_appointment_brief_d3664f5")}</p><span className="hero-pill">{progress.decision === "approved" ? tr("copy.official_handoff_prepared_bae6ba8") : progress.decision === "rejected" ? tr("copy.appointment_deferred_124c390") : tr("copy.appointment_approval_required_7d855ff")}</span><p className="mt-4" role="status">{tr("copy.research_status_627ed67")}{progress.researchStartedAt === null ? tr("copy.ready_to_start_7196e32") : research < 1 ? tr("copy.running_v0_6175a24", { v0: Math.round(research * 100) }) : tr("copy.complete_community_cultural_guide_and_starter_ki_3f29107")}</p><Button variant="secondary" onClick={() => go(7)}>{tr("copy.open_community_cultural_guide_124ec57")}</Button></Card></div></>}

        <section className="hero-conversation" aria-label={tr("copy.talk_to_adapt_c9461e0")}><div className="hero-conversation-controls"><Volume2 className="size-5 text-primary" aria-hidden /><strong>{tr("copy.keep_talking_to_adapt_6a2c844")}</strong><select aria-label={tr("copy.demo_conversation_question_c966058")} value={question} onChange={(e) => setQuestion(e.target.value as typeof question)}><option value="first">{tr("copy.what_should_i_do_first_df97243")}</option><option value="blockers">{tr("copy.what_s_holding_us_up_a8212b5")}</option><option value="connect">{tr("copy.how_can_we_connect_915acc7")}</option></select><Button variant="secondary" onClick={() => speak(scriptedAnswer(question))}>{tr("copy.ask_adapt_07a99fc")}</Button>{dictation.supported && <Button variant="ghost" onClick={dictation.listening ? dictation.stop : dictation.start}>{dictation.listening ? tr("copy.stop_listening_e134211") : tr("copy.talk_reconnect_2fd3cbd")}</Button>}</div>{reply && <p className="hero-reply" aria-live="polite">{localize(reply)}</p>}{(dictation.listening || dictation.error || audioNote) && <p role="status" className="hero-caption">{dictation.listening ? tr("copy.listening_raw_audio_and_transcripts_are_not_save_c7dfbb4") : dictation.error ?? audioNote}</p>}</section>
        <footer className="hero-footer"><p>{tr("copy.recorded_demo_synthetic_data_source_dates_retain_1063877")}</p><div className="hero-buttons"><Button variant="ghost" disabled={scene === 0} icon={<ChevronLeft className="size-4" />} onClick={() => go(scene - 1)}>{tr("copy.back_b52b36b")}</Button><Button disabled={scene === 9} onClick={() => go(scene + 1)}>{tr("copy.continue_2e02623")}<ChevronRight className="size-4" /></Button></div></footer>
      </main>
    </div>
  </div>;
}
