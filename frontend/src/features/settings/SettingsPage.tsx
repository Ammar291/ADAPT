import { tr, localize, useLocale } from "@/i18n";
import { ChevronLeft, LogOut, Monitor, Moon, ShieldCheck, Sun } from "lucide-react";
import { useEffect, useId, useMemo, useState } from "react";
import { Link } from "react-router";
import { Button, buttonClass } from "@/components/ui/Button";
import { Select } from "@/components/ui/Field";
import { LanguageSelector } from "@/i18n/LanguageSelector";
import { PageHeader } from "@/components/ui/PageHeader";
import { ErrorState, Skeleton, SkeletonText } from "@/components/ui/States";
import { toast } from "@/components/ui/Toast";
import type { Preferences } from "@/domain/profile";
import { describeError } from "@/lib/api/errors";
import { useProfile, useSaveProfile, useSession, useSignOut, useUpdatePreferences } from "@/lib/api/hooks";
import { usePwaInstall } from "@/lib/hooks/usePwaInstall";
import { useServices } from "@/services/context";
import { browserLanguages, languageName } from "@/lib/languages";
import { useUiStore, type ThemePreference } from "@/stores/ui";
import { FAITH_LABEL } from "@/features/profile/summary";
import { InstallControl } from "./InstallApp";
import { COMMUNITY_OPTIONS, consentValue, FAITH_OPTIONS, languageOptions, suggestedLanguages, type Consent } from "./preferences";
import { OptionGroup, SettingGroup, SettingRow, type Option, type SaveState } from "./SettingRow";

type ToastMessage = { title: string; description?: string };

function saveFailed(error: unknown) {
  const { detail } = describeError(error);
  toast({ tone: "error", title: tr("copy.your_change_wasn_t_saved_c711661"), description: detail || tr("copy.check_your_connection_and_try_again_563862b") });
}

/**
 * One preference, saved as soon as it changes. While the request is in flight the control
 * already shows the new value (the mutation's variables), so it feels instant; on failure it
 * falls back to the saved value and says so.
 */
function usePreference<K extends keyof Preferences>(key: K, saved: Preferences[K] | undefined, message: (value: Preferences[K]) => ToastMessage) {
  const mutation = useUpdatePreferences();
  const [justSaved, setJustSaved] = useState(false);

  useEffect(() => {
    if (!justSaved) return;
    const timer = setTimeout(() => setJustSaved(false), 2500);
    return () => clearTimeout(timer);
  }, [justSaved]);

  const pendingValue = mutation.isPending ? (mutation.variables?.[key] as Preferences[K] | undefined) : undefined;
  const value = pendingValue ?? saved;
  const state: SaveState = mutation.isPending ? "saving" : justSaved ? "saved" : "idle";

  const set = (next: Preferences[K], onSaved?: () => void) => {
    if (next === value) return;
    setJustSaved(false);
    mutation.mutate({ [key]: next } as Partial<Preferences>, {
      onSuccess: () => {
        setJustSaved(true);
        toast(message(next));
        onSaved?.();
      },
      onError: saveFailed,
    });
  };

  return { value, set, state };
}

function LanguageRow({ saved }: { saved: string }) {
  const uiLocale = useLocale();
  const titleId = useId();
  const pref = usePreference("preferredLanguage", saved, (code) => ({
    title: tr("copy.adapt_will_talk_to_you_in_v0_2f56d6a", { v0: languageName(code) }),
    description: tr("copy.by_voice_and_in_text_from_your_next_message_fdc66f6"),
  }));
  const options = useMemo(() => languageOptions(pref.value ?? saved), [pref.value, saved, uiLocale]);
  const suggested = useMemo(() => suggestedLanguages(browserLanguages(), options), [options, uiLocale]);

  return (
    <SettingRow
      titleId={titleId}
      title={tr("copy.conversation_language_9d08c8f")}
      state={pref.state}
      description={tr("copy.adapt_talks_and_writes_to_you_in_this_language_b_09f836c")}
      control={
        <div className="w-full md:w-72 [&_select]:h-11 md:[&_select]:h-10">
          <Select aria-labelledby={titleId} value={pref.value ?? saved} onChange={(event) => pref.set(event.target.value)}>
            {suggested.length > 0 && (
              <optgroup label={tr("copy.your_browser_s_languages_bb1e381")}>
                {suggested.map((option) => (
                  <option key={`suggested-${option.value}`} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </optgroup>
            )}
            <optgroup label={tr("copy.all_languages_56488c3")}>
              {options.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </optgroup>
          </Select>
        </div>
      }
    />
  );
}

function VoiceTranscriptsRow({ saved }: { saved: boolean }) {
  useLocale();
  const titleId = useId();
  const pref = usePreference("voiceTranscriptsRetained", saved, (keep) =>
    keep
      ? { title: tr("copy.voice_transcripts_will_be_kept_60447eb"), description: tr("copy.you_can_read_back_what_was_said_in_voice_convers_bd1fdc8") }
      : { title: tr("copy.voice_transcripts_won_t_be_kept_af5f4ad"), description: tr("copy.the_text_of_each_voice_conversation_is_discarded_61cd673") },
  );
  const options: Option<"keep" | "discard">[] = [
    { value: "keep", label: tr("copy.keep_466fc49") },
    { value: "discard", label: tr("copy.don_t_keep_64f7770") },
  ];
  return (
    <SettingRow
      titleId={titleId}
      title={tr("copy.voice_transcripts_29910ec")}
      state={pref.state}
      description={tr("copy.keep_a_written_record_of_your_voice_conversation_37d214d")}
      control={<OptionGroup name="voice-transcripts" labelledBy={titleId} value={pref.value ? "keep" : "discard"} options={options} onChange={(v) => pref.set(v === "keep")} />}
    />
  );
}

function CommunityRow({ saved }: { saved: Preferences["communityPersonalization"] }) {
  useLocale();
  const titleId = useId();
  const pref = usePreference("communityPersonalization", saved, (status) =>
    status === "granted"
      ? { title: tr("copy.community_suggestions_personalised_c6de133"), description: tr("copy.discover_will_use_your_background_languages_and__b6157c9") }
      : { title: tr("copy.community_suggestions_kept_general_82a9508"), description: tr("copy.discover_will_show_the_same_suggestions_any_newc_3b964ee") },
  );
  return (
    <SettingRow
      titleId={titleId}
      title={tr("copy.community_suggestions_980384c")}
      state={pref.state}
      description={
        <>
          {tr("copy.discover_can_use_your_background_languages_and_i_df55eae")}{pref.value === "not_asked" && <span className="mt-1 block text-subtle">{tr("copy.you_haven_t_chosen_yet_so_suggestions_stay_gener_3645308")}</span>}
        </>
      }
      control={
        <OptionGroup<Consent>
          name="community-personalisation"
          labelledBy={titleId}
          value={consentValue(pref.value ?? saved)}
          options={COMMUNITY_OPTIONS}
          onChange={(v) => pref.set(v)}
        />
      }
    />
  );
}

function FaithRow({ saved }: { saved: Preferences["faithPersonalization"] }) {
  useLocale();
  const titleId = useId();
  const profile = useProfile();
  const saveProfile = useSaveProfile();
  const pref = usePreference("faithPersonalization", saved, (status) =>
    status === "granted"
      ? { title: tr("copy.places_of_worship_included_36713eb"), description: tr("copy.discover_can_now_show_places_of_worship_you_can__8fbc8d1") }
      : { title: tr("copy.places_of_worship_left_out_0486fd7"), description: tr("copy.adapt_won_t_show_places_of_worship_or_keep_your__065e2c8") },
  );

  const onChange = (next: Consent) =>
    pref.set(next, () => {
      // Declining also removes the faith the user shared, not just its use.
      const current = profile.data;
      if (next === "declined" && current?.faith) saveProfile.mutate({ ...current, faith: null });
    });

  const shared = pref.value === "granted" ? profile.data?.faith : null;

  return (
    <SettingRow
      titleId={titleId}
      title={tr("copy.places_of_worship_a018ec3")}
      state={pref.state}
      description={
        <>
          {tr("copy.show_mosques_churches_temples_and_other_places_o_a877bf8")}{pref.value === "not_asked" && <span className="mt-1 block text-subtle">{tr("copy.you_haven_t_chosen_yet_so_discover_leaves_them_o_7530502")}</span>}
        </>
      }
      footer={shared ? <p className="mt-2 text-sm">{tr("copy.showing_places_of_worship_for_82623b4")}{FAITH_LABEL[shared]}</p> : null}
      control={<OptionGroup<Consent> name="faith-personalisation" labelledBy={titleId} value={consentValue(pref.value ?? saved)} options={FAITH_OPTIONS} onChange={onChange} />}
    />
  );
}

const THEME_OPTIONS: Option<ThemePreference>[] = [
  { value: "system", label: tr("copy.match_device_15360c2", { lng: "en" }), icon: <Monitor className="size-4" aria-hidden /> },
  { value: "light", label: tr("copy.light_a36ef8a", { lng: "en" }), icon: <Sun className="size-4" aria-hidden /> },
  { value: "dark", label: tr("copy.dark_ae1ef01", { lng: "en" }), icon: <Moon className="size-4" aria-hidden /> },
];

function ThemeRow() {
  useLocale();
  const titleId = useId();
  const theme = useUiStore((s) => s.theme);
  const setTheme = useUiStore((s) => s.setTheme);
  return (
    <SettingRow
      titleId={titleId}
      title={tr("copy.theme_a797e30")}
      description={tr("copy.match_your_device_or_always_use_light_or_dark_sa_ef8f076")}
      control={<OptionGroup name="theme" labelledBy={titleId} value={theme} options={THEME_OPTIONS} onChange={setTheme} />}
    />
  );
}

function InstallRow() {
  useLocale();
  const pwa = usePwaInstall();
  if (pwa.installed) return null;
  // A prompt is a real control; otherwise the steps belong under the explanation.
  return (
    <SettingRow
      title={tr("copy.install_adapt_250d11f")}
      description={tr("copy.open_adapt_from_your_home_screen_or_dock_full_sc_a3adca7")}
      control={pwa.canPrompt ? <InstallControl /> : null}
      footer={pwa.canPrompt ? null : <InstallControl className="mt-3" />}
    />
  );
}

function SignOutRow({ isDemo }: { isDemo: boolean }) {
  useLocale();
  const signOut = useSignOut();
  return (
    <SettingRow
      title={tr("copy.sign_out_dc1649a")}
      description={
        isDemo
          ? tr("copy.ends_your_session_on_this_device_this_is_a_priva_adacfea")
          : tr("copy.ends_your_session_on_this_device_your_plan_and_d_c0bda95")
      }
      control={
        <div className="[&>button]:h-11 [&>button]:w-full md:[&>button]:h-10 md:[&>button]:w-auto">
          <Button
            variant="secondary"
            loading={signOut.isPending}
            icon={<LogOut className="flip-rtl size-4" aria-hidden />}
            onClick={() =>
              signOut.mutate(undefined, {
                onSuccess: () => window.location.assign("/"),
                onError: (error) => toast({ tone: "error", title: tr("copy.you_re_still_signed_in_da1044d"), description: describeError(error).detail || tr("copy.check_your_connection_and_try_again_563862b") }),
              })
            }
          >
            {tr("copy.sign_out_dc1649a")}</Button>
        </div>
      }
    />
  );
}

function SettingsSkeleton() {
  useLocale();
  return (
    <div role="status" aria-label={tr("copy.loading_your_settings_00625da")} className="flex flex-col gap-8">
      {[2, 2, 1].map((rows, i) => (
        <div key={i}>
          <Skeleton className="mb-3 h-5 w-40" />
          <div className="divide-y divide-line rounded-lg border border-line bg-surface">
            {localize(Array.from({ length: rows }, (_, j) => (
              <div key={j} className="flex flex-col gap-3 p-5 md:flex-row md:justify-between">
                <SkeletonText lines={2} className="md:w-1/2" />
                <Skeleton className="h-10 w-full md:w-56" />
              </div>
            )))}
          </div>
        </div>
      ))}
    </div>
  );
}

function DemoRow() {
  useLocale();
  const { scenarios } = useServices();
  if (!scenarios) return null;
  return (
    <SettingRow
      title={tr("copy.founder_arrival_demo_48e2f15")}
      description={tr("copy.a_scripted_run_of_adapt_s_real_pipeline_on_synth_63975d5")}
      control={
        <Link to="/demo/founder-arrival" className={buttonClass("secondary", "sm")}>
          {tr("copy.open_cf9b770")}</Link>
      }
    />
  );
}

export default function SettingsPage() {
  useLocale();
  const session = useSession();

  return (
    <div className="flex w-full max-w-3xl flex-col">
      <Link to="/profile" className="-ms-1 mb-3 inline-flex h-11 w-fit items-center gap-1 rounded-md px-1 text-sm text-muted hover:text-ink lg:hidden">
        <ChevronLeft className="flip-rtl size-4" aria-hidden />
        {tr("copy.profile_ff4fc02")}</Link>
      <PageHeader title={tr("copy.settings_c7f73bb")} description={tr("copy.language_privacy_and_how_adapt_looks_changes_sav_778214b")} />

      {session.isPending && <SettingsSkeleton />}
      {session.isError && <ErrorState error={session.error} onRetry={() => void session.refetch()} />}

      {session.data && (
        <div className="flex flex-col gap-8">
          <SettingGroup id="settings-language" title={tr("language.interface")} description={tr("language.description")}>
            <LanguageSelector className="w-full md:w-72" />
          </SettingGroup>
          <SettingGroup id="settings-conversation" title={tr("copy.conversation_2a20c75")}>
            <LanguageRow saved={session.data.preferences.preferredLanguage} />
            <VoiceTranscriptsRow saved={session.data.preferences.voiceTranscriptsRetained} />
          </SettingGroup>

          <SettingGroup id="settings-personalisation" title={tr("copy.personalisation_8ef1c70")} description={tr("copy.what_discover_may_use_to_tailor_its_suggestions__75e3d63")}>
            <CommunityRow saved={session.data.preferences.communityPersonalization} />
            <FaithRow saved={session.data.preferences.faithPersonalization} />
          </SettingGroup>

          <SettingGroup id="settings-appearance" title={tr("copy.appearance_41def7a")}>
            <ThemeRow />
          </SettingGroup>

          <SettingGroup id="settings-device" title={tr("copy.this_device_fa5a6dd")}>
            <InstallRow />
            <DemoRow />
            <SignOutRow isDemo={session.data.isDemo} />
          </SettingGroup>

          <aside aria-label={tr("copy.how_adapt_stores_your_data_5d53917")} className="flex items-start gap-3 border-t border-line pt-6 text-sm text-muted">
            <ShieldCheck className="mt-0.5 size-5 shrink-0 text-primary" aria-hidden />
            <p className="max-w-prose">
              {tr("copy.your_documents_are_encrypted_and_never_stored_on_d140984")}</p>
          </aside>
        </div>
      )}
    </div>
  );
}
