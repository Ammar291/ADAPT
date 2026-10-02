import { LanguageSelector } from "@/i18n/LanguageSelector";
import { tr, localize, useLocale } from "@/i18n";
import { AlertCircle, ArrowLeft, BadgeCheck, Check, FileText, Lock, Mic, MicOff, Minus, Plus, ShieldCheck, Upload, X } from "lucide-react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Link, useNavigate } from "react-router";
import { BrandMark, Wordmark } from "@/app/layout/BrandMark";
import { Toaster } from "@/components/ui/Toast";
import { Button } from "@/components/ui/Button";
import { TextArea, TextInput } from "@/components/ui/Field";
import { Spinner } from "@/components/ui/Spinner";
import { ErrorState } from "@/components/ui/States";
import type { DocumentKind } from "@/domain/documents";
import {
  COMPANY_TIMING_LABEL,
  HOUSEHOLD_LABEL,
  MOVE_TYPE_LABEL,
  hasChildren,
  hasSpouse,
  type CompanyTiming,
  type FaithCommunity,
  type Household,
  type MoveProfile,
  type MoveType,
} from "@/domain/profile";
import { pipelineOf, UPLOAD_ACCEPT, validateUpload } from "@/features/documents/lib/documents";
import { describeError } from "@/lib/api/errors";
import {
  useActiveJourney,
  useDeleteDocument,
  useDemo,
  useDocuments,
  useSaveProfile,
  useSession,
  useStartJourney,
  useUpdatePreferences,
  useUploadDocument,
} from "@/lib/api/hooks";
import { cn } from "@/lib/cn";
import { formatDate } from "@/lib/format";
import { browserLanguages, languageName, searchLanguages } from "@/lib/languages";
import { composePrompt, DEFAULT_PROFILE } from "./prompt";
import { useDictation } from "./useDictation";

type StepId = "intro" | "type" | "arrival" | "household" | "company" | "documents" | "languages" | "personal" | "review";
const STEPS: StepId[] = ["intro", "type", "arrival", "household", "company", "documents", "languages", "personal", "review"];

/** Documents onboarding asks for: the ones most of a plan depends on. */
type OnboardingDocument = Extract<DocumentKind, "passport" | "marriage_certificate">;
const DOCUMENT_SLOTS: { kind: OnboardingDocument; title: string; hint: string }[] = [
  { kind: "passport", title: tr("copy.your_passport_e5097f9", { lng: "en" }), hint: tr("copy.the_page_with_your_photo_most_steps_need_it_c172381", { lng: "en" }) },
  { kind: "marriage_certificate", title: tr("copy.your_marriage_certificate_ebe2f0c", { lng: "en" }), hint: tr("copy.for_your_spouse_s_residence_visa_9a35360", { lng: "en" }) },
];

type Consent = "granted" | "declined";

const FAITHS: { value: FaithCommunity; label: string }[] = [
  { value: "all", label: tr("copy.show_all_faiths_4b00d39", { lng: "en" }) },
  { value: "islam", label: tr("copy.islam_4f910da", { lng: "en" }) },
  { value: "christianity", label: tr("copy.christianity_59d48ff", { lng: "en" }) },
  { value: "hinduism", label: tr("copy.hinduism_df9d0c6", { lng: "en" }) },
  { value: "sikhism", label: tr("copy.sikhism_043d45a", { lng: "en" }) },
  { value: "buddhism", label: tr("copy.buddhism_6eb15e6", { lng: "en" }) },
  { value: "judaism", label: tr("copy.judaism_5439569", { lng: "en" }) },
];

const QUESTION: Record<StepId, string> = {
  intro: tr("copy.tell_adapt_about_your_move_0c0d117", { lng: "en" }),
  type: tr("common.b6abf8063c", { lng: "en" }),
  arrival: tr("copy.when_do_you_want_to_arrive_6dbb623", { lng: "en" }),
  household: tr("copy.who_s_moving_with_you_3c303b8", { lng: "en" }),
  company: tr("copy.are_you_starting_a_company_27b7818", { lng: "en" }),
  documents: tr("copy.add_your_documents_9e5c078", { lng: "en" }),
  languages: tr("copy.which_languages_do_you_speak_2831acb", { lng: "en" }),
  personal: tr("copy.how_personal_should_suggestions_be_b1c62de", { lng: "en" }),
  review: tr("copy.here_s_what_adapt_will_plan_around_0fe1dcf", { lng: "en" }),
};

// --- small building blocks ---------------------------------------------------------------------

function Choice({ selected, onSelect, children, description }: { selected: boolean; onSelect: () => void; children: ReactNode; description?: string }) {
  useLocale();
  return (
    <button
      type="button"
      role="radio"
      aria-checked={selected}
      onClick={onSelect}
      className={cn(
        "group flex min-h-12 w-full items-center gap-3 rounded-lg border px-4 py-3 text-start transition-colors",
        selected ? "border-ink bg-ink text-canvas" : "border-line-strong bg-surface hover:border-ink/50",
      )}
    >
      <span className="min-w-0 flex-1">
        <span className="block font-medium">{localize(children)}</span>
        {description && <span className={cn("mt-0.5 block text-sm", selected ? "text-canvas/75" : "text-muted")}>{localize(description)}</span>}
      </span>
      <span
        className={cn(
          "flex size-5 shrink-0 items-center justify-center rounded-full border",
          selected ? "border-canvas bg-canvas text-ink" : "border-line-strong",
        )}
        aria-hidden
      >
        {selected && <Check className="size-3.5" />}
      </span>
    </button>
  );
}

function ChoiceGroup({ label, children, columns = 1 }: { label: string; children: ReactNode; columns?: 1 | 2 }) {
  useLocale();
  return (
    <div role="radiogroup" aria-label={localize(label)} className={cn("grid gap-2", columns === 2 && "sm:grid-cols-2")} onKeyDown={(e) => {
      if (!["ArrowDown", "ArrowUp", "ArrowLeft", "ArrowRight", "Home", "End"].includes(e.key)) return;
      const choices = Array.from(e.currentTarget.querySelectorAll<HTMLButtonElement>('[role="radio"]'));
      const current = choices.indexOf(document.activeElement as HTMLButtonElement);
      const rtl = getComputedStyle(e.currentTarget).direction === "rtl";
      const forward = e.key === "ArrowDown" || e.key === (rtl ? "ArrowLeft" : "ArrowRight");
      const next = e.key === "Home" ? 0 : e.key === "End" ? choices.length - 1 : (current + (forward ? 1 : -1) + choices.length) % choices.length;
      e.preventDefault(); choices[next]?.focus();
    }}>
      {localize(children)}
    </div>
  );
}

/** The quiet navy panel beside the conversation on desktop: what ADAPT promises. */
function BrandPanel() {
  useLocale();
  const lines = [
    { color: "var(--lane-business)", y: 70, stops: [60, 150, 240, 330] },
    { color: "var(--lane-residency)", y: 130, stops: [120, 210, 300, 390] },
    { color: "var(--lane-family)", y: 190, stops: [180, 300, 420] },
    { color: "var(--lane-housing)", y: 250, stops: [90, 250, 360] },
  ];
  return (
    <aside className="sticky top-0 hidden h-dvh w-[42%] max-w-[560px] shrink-0 flex-col justify-between overflow-hidden bg-[#0f1c2e] p-10 text-[#e7ecf3] lg:flex">
      <div className="flex items-center gap-2.5">
        <BrandMark className="size-9" />
        <span className="font-display text-lg font-semibold tracking-tight">{tr("copy.adapt_2e26648")}</span>
      </div>
      <div className="relative">
        <svg viewBox="0 0 460 300" className="mb-10 w-full max-w-md" aria-hidden>
          {lines.map((line) => (
            <g key={line.y}>
              <path d={`M20 ${line.y} H440`} stroke={line.color} strokeOpacity="0.5" strokeWidth="2" strokeLinecap="round" />
              {line.stops.map((x, i) => (
                <circle
                  key={x}
                  cx={x}
                  cy={line.y}
                  r="7"
                  fill={i === 0 ? line.color : "#0f1c2e"}
                  stroke={line.color}
                  strokeWidth="2.5"
                />
              ))}
            </g>
          ))}
          <path d="M150 70 C 180 70, 180 130, 210 130" stroke="#e7ecf3" strokeOpacity="0.25" strokeWidth="1.5" fill="none" strokeDasharray="4 4" />
          <path d="M300 130 C 330 130, 330 190, 360 190" stroke="#e7ecf3" strokeOpacity="0.25" strokeWidth="1.5" fill="none" strokeDasharray="4 4" />
          <path d="M360 250 C 390 250, 390 190, 420 190" stroke="#e7ecf3" strokeOpacity="0.25" strokeWidth="1.5" fill="none" strokeDasharray="4 4" />
        </svg>
        <h2 className="max-w-md font-display text-4xl leading-tight text-[#f5f4f0]">{tr("copy.your_move_to_abu_dhabi_planned_around_you_41fb8fe")}</h2>
        <p className="mt-4 max-w-md text-[#a1acbb]">
          {tr("copy.company_residency_housing_and_family_steps_in_th_c341ba0")}</p>
      </div>
      <ul className="flex flex-col gap-3 text-sm text-[#c9d1dc]">
        <li className="flex gap-3">
          <BadgeCheck className="size-4 shrink-0 text-[#4db6bc]" aria-hidden />
          {tr("copy.every_requirement_links_to_the_government_page_i_e74b641")}</li>
        <li className="flex gap-3">
          <ShieldCheck className="size-4 shrink-0 text-[#4db6bc]" aria-hidden />
          {tr("copy.nothing_is_sent_booked_or_submitted_without_your_11af244")}</li>
        <li className="flex gap-3">
          <Lock className="size-4 shrink-0 text-[#4db6bc]" aria-hidden />
          {tr("copy.your_details_stay_private_to_you_and_are_never_s_b4042da")}</li>
      </ul>
    </aside>
  );
}

function LanguagePicker({ value, onChange }: { value: string[]; onChange: (codes: string[]) => void }) {
  const uiLocale = useLocale();
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const results = useMemo(() => searchLanguages(query, value), [query, value, uiLocale]);
  const quick = useMemo(() => browserLanguages().filter((c) => !value.includes(c)), [value, uiLocale]);
  const add = (code: string) => {
    onChange([...value, code]);
    setQuery("");
    setActive(0);
  };
  return (
    <div className="flex flex-col gap-3">
      {value.length > 0 && (
        <ul className="flex flex-wrap gap-2" aria-label={tr("copy.languages_you_chose_7bd6bbb")}>
          {value.map((code) => (
            <li key={code} className="inline-flex h-9 items-center gap-1 rounded-full bg-ink ps-3 pe-1 text-sm text-canvas">
              {localize(languageName(code))}
              <button
                type="button"
                onClick={() => onChange(value.filter((c) => c !== code))}
                className="flex size-7 items-center justify-center rounded-full hover:bg-canvas/15"
                aria-label={localize(tr("copy.remove_v0_f7ef029", { v0: languageName(code) }))}
              >
                <X className="size-3.5" aria-hidden />
              </button>
            </li>
          ))}
        </ul>
      )}
      <div className="relative">
        <label htmlFor="language-search" className="sr-only">
          {tr("copy.search_languages_ea93e61")}</label>
        <TextInput
          id="language-search"
          role="combobox"
          aria-expanded={results.length > 0}
          aria-controls="language-results"
          aria-activedescendant={results[active] ? `lang-${results[active]!.code}` : undefined}
          autoComplete="off"
          value={query}
          placeholder={tr("copy.start_typing_a_language_c87423f")}
          onChange={(e) => {
            setQuery(e.target.value);
            setActive(0);
          }}
          onKeyDown={(e) => {
            if (e.key === "ArrowDown") {
              e.preventDefault();
              setActive((i) => Math.min(i + 1, results.length - 1));
            } else if (e.key === "ArrowUp") {
              e.preventDefault();
              setActive((i) => Math.max(i - 1, 0));
            } else if (e.key === "Enter" && results[active]) {
              e.preventDefault();
              add(results[active]!.code);
            }
          }}
          className="h-12 text-base"
        />
        {results.length > 0 && (
          <ul id="language-results" role="listbox" className="absolute inset-x-0 top-full z-10 mt-1 overflow-hidden rounded-lg border border-line bg-surface shadow-overlay">
            {results.map((lang, i) => (
              <li
                key={lang.code}
                id={`lang-${lang.code}`}
                role="option"
                aria-selected={i === active}
                onMouseDown={(e) => {
                  e.preventDefault();
                  add(lang.code);
                }}
                onMouseEnter={() => setActive(i)}
                className={cn("flex cursor-pointer items-baseline justify-between gap-3 px-4 py-2.5 text-sm", i === active && "bg-sunken")}
              >
                <span>{localize(lang.name)}</span>
                {lang.autonym !== lang.name && <span className="text-muted" lang={lang.code}>{localize(lang.autonym)}</span>}
              </li>
            ))}
          </ul>
        )}
      </div>
      {quick.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <span className="text-muted">{tr("copy.from_your_browser_662f654")}</span>
          {quick.map((code) => (
            <button
              key={code}
              type="button"
              onClick={() => add(code)}
              className="inline-flex h-9 items-center gap-1 rounded-full border border-line-strong px-3 hover:border-ink/50"
            >
              <Plus className="size-3.5" aria-hidden />
              {localize(languageName(code))}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/**
 * One document to add during onboarding. The file goes straight to the documents service;
 * what ADAPT read from it (and whether it's still reading) always comes from the server.
 */
function DocumentSlot({
  kind,
  title,
  hint,
  documentId,
  onUploaded,
}: {
  kind: OnboardingDocument;
  title: string;
  hint: string;
  documentId: string | undefined;
  onUploaded: (id: string) => void;
}) {
  useLocale();
  const upload = useUploadDocument();
  const remove = useDeleteDocument();
  const documents = useDocuments();
  const input = useRef<HTMLInputElement>(null);
  const [error, setError] = useState<string | null>(null);
  const doc = documentId ? documents.data?.find((d) => d.id === documentId) : undefined;
  const status = doc ? pipelineOf(doc.status) : null;

  const choose = async (file: File | undefined) => {
    if (!file) return;
    const check = validateUpload(file);
    if (!check.ok) {
      setError(check.message);
      return;
    }
    setError(null);
    try {
      const created = await upload.mutateAsync({ file, kind });
      onUploaded(created.id);
      // Replacing: the earlier file and everything read from it go, so it can't shape the plan.
      if (documentId) remove.mutate(documentId);
    } catch (err) {
      setError(describeError(err).title);
    } finally {
      if (input.current) input.current.value = "";
    }
  };

  let line: ReactNode = hint;
  if (upload.isPending) line = tr("copy.uploading_privately_53048bc");
  else if (doc && status) {
    const icon = status.busy ? (
      <Spinner className="size-3.5" />
    ) : status.tone === "failed" ? (
      <AlertCircle className="size-3.5 text-danger" aria-hidden />
    ) : (
      <Check className="size-3.5 text-primary" aria-hidden />
    );
    const text = status.tone === "attention" ? tr("copy.read_you_ll_check_a_few_details_while_adapt_plan_351c02f") : status.label;
    line = (
      <span className="inline-flex items-center gap-1.5">
        {localize(icon)}
        {localize(text)}
      </span>
    );
  } else if (documentId) line = "Uploaded";

  return (
    <div className="flex flex-wrap items-center gap-3 rounded-lg border border-line-strong bg-surface p-4">
      <span className="flex size-10 shrink-0 items-center justify-center rounded-full bg-sunken" aria-hidden>
        <FileText className="size-5 text-muted" />
      </span>
      <div className="min-w-0 flex-1">
        <p className="font-medium">{localize(title)}</p>
        <p className="text-sm text-muted" aria-live="polite">
          {doc ? <span className="me-1 break-all">{doc.filename}{tr("copy.text_05a79f0")}</span> : null}
          {localize(line)}
        </p>
        {error && (
          <p role="alert" className="mt-1 text-sm text-danger">
            {localize(error)}
          </p>
        )}
      </div>
      <input
        ref={input}
        type="file"
        accept={UPLOAD_ACCEPT}
        className="sr-only"
        tabIndex={-1}
        aria-label={localize(tr("copy.upload_v0_5aec9e5", { v0: title.replace(/^Your /, "your ") }))}
        onChange={(e) => void choose(e.target.files?.[0])}
      />
      <Button variant="secondary" size="sm" loading={upload.isPending} onClick={() => input.current?.click()} icon={<Upload className="size-4" aria-hidden />}>
        {documentId ? tr("copy.replace_a7cf7b2") : tr("copy.upload_8bdf057")}
      </Button>
    </div>
  );
}

// --- page ------------------------------------------------------------------------------------------

export default function OnboardingPage() {
  const uiLocale = useLocale();
  const navigate = useNavigate();
  const session = useSession();
  const existing = useActiveJourney();
  const demo = useDemo();
  const updatePreferences = useUpdatePreferences();
  const startJourney = useStartJourney();
  const saveProfile = useSaveProfile();
  const reduceMotion = useReducedMotion();

  const [step, setStep] = useState<StepId>("intro");
  const [profile, setProfile] = useState<MoveProfile>(DEFAULT_PROFILE);
  const [answered, setAnswered] = useState<Set<StepId>>(new Set());
  const [note, setNote] = useState("");
  const [usedVoice, setUsedVoice] = useState(false);
  const [communityConsent, setCommunityConsent] = useState<Consent | null>(null);
  const [faithConsent, setFaithConsent] = useState<Consent | null>(null);
  const [flexible, setFlexible] = useState(false);
  // Which uploads belong to this plan (ids only); their contents and status live on the server.
  const [attached, setAttached] = useState<Partial<Record<OnboardingDocument, string>>>({});
  const slots = DOCUMENT_SLOTS.filter((slot) => slot.kind === "passport" || hasSpouse(profile.household));
  const focusHeading = useCallback((node: HTMLHeadingElement | null) => {
    if (!node) return;
    const frame = requestAnimationFrame(() => {
      if (!node.isConnected) return;
      node.focus({ preventScroll: true });
      node.scrollIntoView({ behavior: reduceMotion ? "auto" : "smooth", block: "nearest" });
    });
    return () => cancelAnimationFrame(frame);
  }, [reduceMotion, uiLocale]);

  const dictation = useDictation((text) => {
    setUsedVoice(true);
    setNote((current) => (current ? `${current.trimEnd()} ${text}` : text));
  });

  const stepIndex = STEPS.indexOf(step);
  const update = (patch: Partial<MoveProfile>) => setProfile((p) => ({ ...p, ...patch }));
  const goTo = (next: StepId) => setStep(next);
  const complete = (id: StepId, next?: StepId) => {
    setAnswered((set) => new Set(set).add(id));
    const nextStep = next ?? STEPS[STEPS.indexOf(id) + 1]!;
    // Once everything is answered, changes go straight back to the review.
    goTo(answered.has("review") ? "review" : nextStep);
  };
  const back = () => goTo(STEPS[Math.max(0, stepIndex - 1)]!);

  useEffect(() => { document.title = `Plan your move · ADAPT`; }, []);

  const today = new Date().toISOString().slice(0, 10);
  const name = session.data?.displayName?.split(" ")[0];

  const summary: { id: StepId; answer: string }[] = [
    { id: "intro", answer: note.trim() ? note.trim() : tr("copy.answered_with_quick_questions_64a8fd2") },
    { id: "type", answer: MOVE_TYPE_LABEL[profile.moveType] },
    { id: "arrival", answer: profile.arrivalDate ? `Arriving ${formatDate(profile.arrivalDate)}` : tr("copy.flexible_8bb749a") },
    {
      id: "household",
      answer: `${HOUSEHOLD_LABEL[profile.household]}${hasChildren(profile.household) ? `, ${profile.childrenCount} ${profile.childrenCount === 1 ? "child" : "children"}` : ""}`,
    },
    { id: "company", answer: profile.companyTiming === "none" ? tr("copy.no_company_5f4283d") : COMPANY_TIMING_LABEL[profile.companyTiming] },
    {
      id: "documents",
      answer: slots.filter((d) => attached[d.kind]).map((d) => d.title.replace(/^Your (.)/, (_, c: string) => c.toUpperCase())).join(", ") || tr("copy.none_yet_80e9901"),
    },
    { id: "languages", answer: profile.languages.length ? profile.languages.map(languageName).join(", ") : tr("copy.skipped_5a000ad") },
    {
      id: "personal",
      answer: [
        communityConsent === "granted" ? tr("copy.personalised_communities_119dbca") : tr("copy.general_communities_c3d6f5f"),
        faithConsent === "granted" ? `places of worship (${FAITHS.find((f) => f.value === (profile.faith ?? "all"))?.label.toLowerCase()})` : tr("copy.no_faith_suggestions_8937ff3"),
      ].join(", "),
    },
  ];
  const history = step === "review" ? [] : summary.filter((s) => answered.has(s.id) && s.id !== step && STEPS.indexOf(s.id) < stepIndex);

  const submit = async () => {
    const finalProfile: MoveProfile = { ...profile, note: note.trim(), faith: faithConsent === "granted" ? profile.faith ?? "all" : null };
    await updatePreferences.mutateAsync({
      communityPersonalization: communityConsent ?? "declined",
      faithPersonalization: faithConsent ?? "declined",
    });
    await saveProfile.mutateAsync(finalProfile);
    const run = await startJourney.mutateAsync({
      prompt: composePrompt(finalProfile, note),
      language: session.data?.preferences.preferredLanguage ?? "en",
      channel: usedVoice ? "voice" : "text",
      // Only documents that belong to this household (a spouse's certificate is left out if
      // the answer changed to moving alone).
      documentIds: slots.flatMap((d) => (attached[d.kind] ? [attached[d.kind]!] : [])),
      profile: finalProfile,
    });
    navigate(`/agents?run=${run.runId}`);
  };

  const submitting = updatePreferences.isPending || saveProfile.isPending || startJourney.isPending;
  const submitError = updatePreferences.error ?? saveProfile.error ?? startJourney.error;

  const body: Record<StepId, ReactNode> = {
    intro: (
      <div className="flex flex-col gap-4">
        <p className="text-muted">
          {tr("copy.where_you_re_moving_from_who_s_coming_and_what_y_bfc74cc")}</p>
        <div className="rounded-xl border border-line-strong bg-surface shadow-card focus-within:border-primary">
          <label htmlFor="move-note" className="sr-only">
            {tr("copy.describe_your_move_317714f")}</label>
          <TextArea
            id="move-note"
            value={dictation.listening && dictation.interim ? `${note} ${dictation.interim}`.trim() : note}
            onChange={(e) => setNote(e.target.value)}
            rows={4}
            placeholder={tr("copy.for_example_we_re_moving_from_toronto_in_novembe_ded3486")}
            className="resize-none border-0 bg-transparent px-4 pt-4 text-base shadow-none focus-visible:ring-0"
          />
          <div className="flex items-center gap-2 px-3 pb-3">
            {dictation.supported && (
              <Button
                variant={dictation.listening ? "primary" : "secondary"}
                size="sm"
                onClick={dictation.listening ? dictation.stop : dictation.start}
                icon={dictation.listening ? <MicOff className="size-4" aria-hidden /> : <Mic className="size-4" aria-hidden />}
                aria-pressed={dictation.listening}
              >
                {dictation.listening ? tr("copy.stop_9e25347") : tr("copy.speak_7a81719")}
              </Button>
            )}
            <span className="text-xs text-subtle" aria-live="polite">
              {dictation.listening ? tr("copy.listening_your_browser_transcribes_what_you_say_b00130b") : dictation.error}
            </span>
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button size="lg" onClick={() => complete("intro")}>
            {note.trim() ? tr("copy.continue_2e02623") : tr("copy.answer_quick_questions_de68327")}
          </Button>
        </div>
      </div>
    ),
    type: (
      <ChoiceGroup label={localize(QUESTION.type)}>
        {(Object.keys(MOVE_TYPE_LABEL) as MoveType[]).map((type) => (
          <Choice
            key={type}
            selected={answered.has("type") && profile.moveType === type}
            onSelect={() => {
              update({ moveType: type, companyTiming: type === "business" ? "now" : profile.companyTiming === "now" && !answered.has("company") ? "none" : profile.companyTiming });
              complete("type");
            }}
          >
            {localize(MOVE_TYPE_LABEL[type])}
          </Choice>
        ))}
      </ChoiceGroup>
    ),
    arrival: (
      <div className="flex flex-col gap-4">
        <p className="text-muted">{tr("copy.adapt_works_backwards_from_this_date_to_tell_you_9e077f2")}</p>
        <div className="flex flex-wrap items-end gap-3">
          <div className="flex flex-col gap-1.5">
            <label htmlFor="arrival" className="text-sm font-medium">
              {tr("copy.target_arrival_date_899a952")}</label>
            <TextInput
              id="arrival"
              type="date"
              min={today}
              value={profile.arrivalDate ?? ""}
              disabled={flexible}
              onChange={(e) => update({ arrivalDate: e.target.value || null })}
              className="h-12 w-56 text-base"
            />
          </div>
          <Button size="lg" disabled={!flexible && !profile.arrivalDate} onClick={() => complete("arrival")}>
            {tr("copy.continue_2e02623")}</Button>
        </div>
        <label className="flex min-h-11 cursor-pointer items-center gap-3 text-sm">
          <input
            type="checkbox"
            checked={flexible}
            onChange={(e) => {
              setFlexible(e.target.checked);
              if (e.target.checked) update({ arrivalDate: null });
            }}
            className="size-4 accent-[var(--teal)]"
          />
          {tr("copy.i_m_flexible_or_don_t_know_yet_50de856")}</label>
      </div>
    ),
    household: (
      <div className="flex flex-col gap-4">
        <ChoiceGroup label={localize(QUESTION.household)} columns={2}>
          {(Object.keys(HOUSEHOLD_LABEL) as Household[]).map((h) => (
            <Choice
              key={h}
              selected={(answered.has("household") || hasChildren(profile.household)) && profile.household === h}
              onSelect={() => {
                update({ household: h, childrenCount: hasChildren(h) ? Math.max(1, profile.childrenCount) : 0 });
                if (!hasChildren(h)) complete("household");
              }}
            >
              {localize(HOUSEHOLD_LABEL[h])}
            </Choice>
          ))}
        </ChoiceGroup>
        {hasChildren(profile.household) && (
          <div className="flex flex-wrap items-center gap-4 rounded-lg border border-line bg-surface p-4">
            <span className="text-sm font-medium" id="children-label">
              {tr("copy.how_many_children_a6557a3")}</span>
            <div className="flex items-center gap-2" role="group" aria-labelledby="children-label">
              <Button variant="secondary" size="sm" aria-label={tr("copy.fewer_children_52133de")} disabled={profile.childrenCount <= 1} onClick={() => update({ childrenCount: profile.childrenCount - 1 })}>
                <Minus className="size-4" aria-hidden />
              </Button>
              <output className="tabular w-8 text-center text-lg font-medium" aria-live="polite">
                {localize(profile.childrenCount)}
              </output>
              <Button variant="secondary" size="sm" aria-label={tr("copy.more_children_35163b2")} disabled={profile.childrenCount >= 6} onClick={() => update({ childrenCount: profile.childrenCount + 1 })}>
                <Plus className="size-4" aria-hidden />
              </Button>
            </div>
            <Button className="ms-auto" onClick={() => complete("household")}>
              {tr("copy.continue_2e02623")}</Button>
          </div>
        )}
      </div>
    ),
    company: (
      <ChoiceGroup label={localize(QUESTION.company)}>
        {(profile.moveType === "business"
          ? [
              { value: "now" as CompanyTiming, label: tr("copy.now_as_part_of_my_move_66a3f9a"), description: tr("copy.your_residency_can_come_through_your_own_company_b39dfe7") },
              { value: "later" as CompanyTiming, label: tr("copy.after_i_ve_settled_607b0d3"), description: tr("copy.adapt_plans_another_residency_route_for_now_0a2595d") },
            ]
          : [
              { value: "now" as CompanyTiming, label: tr("copy.yes_now_1a36344") },
              { value: "later" as CompanyTiming, label: tr("copy.yes_later_3f91305") },
              { value: "none" as CompanyTiming, label: tr("copy.no_816c52f") },
            ]
        ).map((option) => (
          <Choice
            key={option.value}
            selected={answered.has("company") && profile.companyTiming === option.value}
            description={"description" in option ? option.description : undefined}
            onSelect={() => {
              update({ companyTiming: option.value });
              complete("company");
            }}
          >
            {localize(option.label)}
          </Choice>
        ))}
      </ChoiceGroup>
    ),
    documents: (
      <div className="flex flex-col gap-4">
        <p className="text-muted">
          {tr("copy.optional_adapt_reads_them_to_fill_in_your_plan_a_93c613a")}</p>
        {slots.map((slot) => (
          <DocumentSlot
            key={slot.kind}
            kind={slot.kind}
            title={localize(slot.title)}
            hint={localize(slot.hint)}
            documentId={attached[slot.kind]}
            onUploaded={(id) => setAttached((current) => ({ ...current, [slot.kind]: id }))}
          />
        ))}
        <div>
          <Button size="lg" onClick={() => complete("documents")}>
            {slots.some((slot) => attached[slot.kind]) ? tr("copy.continue_2e02623") : tr("copy.skip_for_now_6fc0960")}
          </Button>
        </div>
      </div>
    ),
    languages: (
      <div className="flex flex-col gap-4">
        <p className="text-muted">{tr("copy.optional_it_helps_adapt_suggest_communities_and__1975ddd")}</p>
        <LanguagePicker value={profile.languages} onChange={(languages) => update({ languages })} />
        <div className="flex gap-2">
          <Button size="lg" onClick={() => complete("languages")}>
            {profile.languages.length ? tr("copy.continue_2e02623") : tr("copy.skip_3da4745")}
          </Button>
        </div>
      </div>
    ),
    personal: (
      <div className="flex flex-col gap-6">
        <fieldset className="flex flex-col gap-2">
          <legend className="mb-2 font-medium">{tr("copy.community_suggestions_980384c")}</legend>
          <ChoiceGroup label={tr("copy.community_suggestions_980384c")} columns={2}>
            <Choice selected={communityConsent === "granted"} onSelect={() => setCommunityConsent("granted")} description={tr("copy.use_your_background_and_interests_ec159ec")}>
              {tr("copy.personalise_them_f427de8")}</Choice>
            <Choice selected={communityConsent === "declined"} onSelect={() => setCommunityConsent("declined")} description={tr("copy.show_general_suggestions_a863cf5")}>
              {tr("copy.keep_them_general_bd131b0")}</Choice>
          </ChoiceGroup>
        </fieldset>
        <fieldset className="flex flex-col gap-2">
          <legend className="mb-1 font-medium">{tr("copy.places_of_worship_a018ec3")}</legend>
          <p className="mb-2 text-sm text-muted">
            {tr("copy.adapt_never_guesses_your_faith_from_your_nationa_7c00871")}</p>
          <ChoiceGroup label={tr("copy.places_of_worship_a018ec3")} columns={2}>
            <Choice selected={faithConsent === "granted"} onSelect={() => setFaithConsent("granted")}>
              {tr("copy.include_them_4d937b8")}</Choice>
            <Choice
              selected={faithConsent === "declined"}
              onSelect={() => {
                setFaithConsent("declined");
                update({ faith: null });
              }}
            >
              {tr("copy.leave_them_out_1d9bb78")}</Choice>
          </ChoiceGroup>
          {faithConsent === "granted" && (
            <div role="radiogroup" aria-label={tr("copy.which_places_of_worship_8709cbf")} className="mt-2 flex flex-wrap gap-2">
              {FAITHS.map((f) => (
                <button
                  key={f.value}
                  type="button"
                  role="radio"
                  aria-checked={(profile.faith ?? "all") === f.value}
                  onClick={() => update({ faith: f.value })}
                  className={cn(
                    "h-10 rounded-full border px-4 text-sm transition-colors",
                    (profile.faith ?? "all") === f.value ? "border-ink bg-ink text-canvas" : "border-line-strong hover:border-ink/50",
                  )}
                >
                  {localize(f.label)}
                </button>
              ))}
            </div>
          )}
        </fieldset>
        <div>
          <Button size="lg" onClick={() => complete("personal")}>
            {communityConsent || faithConsent ? tr("copy.continue_2e02623") : tr("copy.skip_for_now_6fc0960")}
          </Button>
        </div>
      </div>
    ),
    review: (
      <div className="flex flex-col gap-5">
        <dl className="divide-y divide-line overflow-hidden rounded-xl border border-line bg-surface shadow-card">
          {summary.map((item) => (
            <div key={item.id} className="flex items-start gap-4 px-4 py-3">
              <dt className="w-20 shrink-0 text-xs text-muted sm:w-40 sm:text-sm">{localize(QUESTION[item.id].replace(/\?$/, "").replace(tr("copy.tell_adapt_about_your_move_0c0d117"), tr("copy.in_your_words_c93103a")))}</dt>
              <dd className="min-w-0 flex-1 text-sm break-words">{localize(item.answer)}</dd>
              <button type="button" onClick={() => goTo(item.id)} className="min-h-11 shrink-0 text-sm font-medium text-primary-strong underline-offset-4 hover:underline">
                {tr("copy.change_64fbd99")}<span className="sr-only">{tr("copy.text_ceca32e")}{localize(QUESTION[item.id])}</span>
              </button>
            </div>
          ))}
        </dl>
        {submitError && <ErrorState error={submitError} onRetry={() => void submit()} />}
        <div className="flex flex-wrap items-center gap-3">
          <Button size="lg" loading={submitting} onClick={() => void submit()}>
            {tr("copy.build_my_plan_2889068")}</Button>
          <p className="text-sm text-muted">{tr("copy.takes_about_15_seconds_you_can_watch_each_step_a9dbf8c")}</p>
        </div>
      </div>
    ),
  };

  return (
    <div className="flex min-h-dvh bg-canvas">
      <BrandPanel />
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="pt-safe sticky top-0 z-10 border-b border-line bg-canvas/95 backdrop-blur-sm">
          <div className="mx-auto flex h-16 max-w-2xl items-center gap-4 px-5">
            <Wordmark className="lg:hidden" />
            <LanguageSelector className="ms-auto" />
            <div className="hidden flex-1 lg:block" />
            <div className="flex flex-1 items-center gap-3 lg:flex-none">
              <div
                className="h-1.5 flex-1 overflow-hidden rounded-full bg-sunken lg:w-48"
                role="progressbar"
                aria-label={tr("copy.onboarding_progress_1fe4ded")}
                aria-valuemin={1}
                aria-valuemax={STEPS.length}
                aria-valuenow={stepIndex + 1}
              >
                <motion.div className="h-full rounded-full bg-primary" animate={{ width: `${((stepIndex + 1) / STEPS.length) * 100}%` }} transition={{ duration: 0.4 }} />
              </div>
              <span className="tabular shrink-0 text-xs text-muted" aria-live="polite">
                {localize(stepIndex + 1)} {tr("copy.of_2449d65")}{localize(STEPS.length)}
              </span>
            </div>
          </div>
        </header>

        <main className="mx-auto flex w-full max-w-2xl flex-1 flex-col px-5 pt-8 pb-16 sm:pt-12">
          {existing.data && (
            <div className="mb-6 rounded-lg border border-line bg-surface p-4 text-sm">
              {tr("copy.you_already_have_a_plan_finishing_this_replaces__92346ce")}{localize(" ")}
              <Link to="/home" className="font-medium text-primary-strong underline underline-offset-4">
                {tr("copy.back_to_my_plan_68e01f2")}</Link>
            </div>
          )}

          {stepIndex === 0 && (
            <p className="mb-3 text-muted">
              {name ? tr("copy.welcome_v0_30c939b", { v0: name }) : tr("copy.welcome_7244864")} {tr("copy.adapt_asks_only_what_it_needs_to_plan_your_move_643f944")}</p>
          )}

          {history.length > 0 && (
            <details className="mb-6 rounded-xl border border-line bg-surface px-4 py-1">
            <summary className="flex min-h-11 cursor-pointer items-center justify-between gap-2 text-sm text-muted"><span>{localize(history.length)} {history.length === 1 ? tr("copy.answer_25dc282") : tr("copy.answers_e3d9bca")} {tr("copy.saved_this_session_42465c1")}</span><span className="text-xs text-primary-strong">{tr("copy.review_answers_6001747")}</span></summary>
            <ol className="flex max-h-64 flex-col gap-3 overflow-y-auto overscroll-contain border-t border-line py-4" aria-label={tr("copy.your_answers_so_far_05edf0a")}>
              {history.map((item) => (
                <li key={item.id} className="flex flex-col gap-1.5">
                  <p className="text-sm text-subtle">{localize(QUESTION[item.id])}</p>
                  <div className="flex items-center justify-end gap-2">
                    <button type="button" onClick={() => goTo(item.id)} className="text-xs text-subtle underline-offset-4 hover:text-ink hover:underline">
                      {tr("copy.change_64fbd99")}</button>
                    <p className="max-w-[85%] rounded-2xl rounded-ee-md bg-sunken px-4 py-2 text-sm">{localize(item.answer)}</p>
                  </div>
                </li>
              ))}
            </ol>
            </details>
          )}

          <AnimatePresence mode="wait" initial={false}>
            <motion.div
              key={step}
              initial={reduceMotion ? false : { opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              exit={reduceMotion ? undefined : { opacity: 0, y: -8, transition: { duration: 0.12 } }}
              transition={{ duration: 0.28, ease: [0.2, 0, 0, 1] }}
              className="flex flex-col gap-5"
            >
              <div className="flex items-start gap-3">
                <BrandMark className="mt-1 size-7" />
                <h1 ref={focusHeading} tabIndex={-1} className="min-w-0 scroll-mt-24 text-2xl leading-snug focus:outline-none sm:text-3xl">
                  {localize(QUESTION[step])}
                </h1>
              </div>
              <div className="sm:ps-10">{localize(body[step])}</div>
            </motion.div>
          </AnimatePresence>

          <div className="mt-10 flex flex-wrap items-center justify-between gap-3 border-t border-line pt-5 sm:ps-10">
            {stepIndex > 0 ? (
              <Button variant="ghost" size="sm" onClick={back} icon={<ArrowLeft className="flip-rtl size-4" aria-hidden />}>
                {tr("copy.back_b52b36b")}</Button>
            ) : (
              <span />
            )}
            {demo && (
              <button
                type="button"
                disabled={demo.seedSample.isPending}
                onClick={() => demo.seedSample.mutate(undefined, { onSuccess: () => navigate("/home") })}
                className="text-sm text-muted underline decoration-line-strong underline-offset-4 hover:text-ink"
              >
                {demo.seedSample.isPending ? tr("copy.loading_the_sample_plan_851e28d") : tr("copy.explore_with_a_sample_plan_99cef7e")}
              </button>
            )}
          </div>
        </main>
        <Toaster />
      </div>
    </div>
  );
}
