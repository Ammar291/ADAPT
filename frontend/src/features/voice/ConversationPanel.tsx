import { tr, localize, useLocale } from "@/i18n";
import { Keyboard, Mic, MicOff, Minimize2, PhoneOff, RotateCcw, X } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { IconButton } from "@/components/ui/Button";
import { Spinner } from "@/components/ui/Spinner";
import { useSystemInfo } from "@/lib/api/hooks";
import { cn } from "@/lib/cn";
import { ScreenWakeLock } from "./audio";
import { Composer } from "./components/Composer";
import { ProblemBanner } from "./components/ProblemBanner";
import { Transcript } from "./components/Transcript";
import { VoiceOrb } from "./components/VoiceOrb";
import { voice } from "./controller";
import { derivePhase, type ConnectionState, type Phase } from "./conversation";
import { selectRunningTool } from "./selectors";
import { dispatch, useVoiceStore } from "./store";
import "./voice.css";

const CAPTION: Record<Phase, string> = {
  idle: tr("copy.tap_to_talk_97e12da", { lng: "en" }),
  requesting_mic: tr("copy.allow_the_microphone_to_start_d07642c", { lng: "en" }),
  connecting: tr("copy.connecting_c1f3b71", { lng: "en" }),
  reconnecting: tr("copy.reconnecting_your_conversation_is_kept_3c7b62d", { lng: "en" }),
  offline: tr("copy.you_re_offline_adapt_reconnects_when_you_re_back_238a0ba", { lng: "en" }),
  ended: tr("copy.tap_to_talk_again_38a26fe", { lng: "en" }),
  failed: tr("copy.voice_stopped_68e9561", { lng: "en" }),
  listening: tr("copy.listening_dc35348", { lng: "en" }),
  muted: tr("copy.muted_b9e78ce", { lng: "en" }),
  user_speaking: tr("copy.listening_dc35348", { lng: "en" }),
  thinking: tr("copy.thinking_d08d8da", { lng: "en" }),
  tool: tr("copy.working_on_it_9f56551", { lng: "en" }),
  speaking: tr("copy.speaking_just_talk_to_interrupt_1769120", { lng: "en" }),
  text: "",
};

const STATUS: Record<ConnectionState, { label: string; tone: "live" | "wait" | "off" }> = {
  idle: { label: tr("copy.not_connected_8b02f3d", { lng: "en" }), tone: "off" },
  requesting_mic: { label: tr("copy.connecting_c1f3b71", { lng: "en" }), tone: "wait" },
  connecting: { label: tr("copy.connecting_c1f3b71", { lng: "en" }), tone: "wait" },
  connected: { label: tr("copy.live_65c821a", { lng: "en" }), tone: "live" },
  reconnecting: { label: tr("copy.reconnecting_9d80f91", { lng: "en" }), tone: "wait" },
  offline: { label: tr("copy.offline_e01fa71", { lng: "en" }), tone: "wait" },
  ended: { label: tr("copy.ended_90303d8", { lng: "en" }), tone: "off" },
  failed: { label: tr("copy.not_connected_8b02f3d", { lng: "en" }), tone: "off" },
};

const EXAMPLES = [
  tr("copy.what_do_i_need_to_sponsor_my_spouse_s_residence__97e16bb", { lng: "en" }),
  tr("copy.what_s_next_in_my_plan_af8ad0f", { lng: "en" }),
  tr("copy.should_i_set_up_my_company_on_the_mainland_or_in_646a344", { lng: "en" }),
];

/** Stable reference, so the orb's animation loop isn't restarted on every render. */
const readLevels = () => voice.levels();

const ACTIVE: ConnectionState[] = ["requesting_mic", "connecting", "connected", "reconnecting", "offline"];

function StatusPill({ connection, text }: { connection: ConnectionState; text: boolean }) {
  useLocale();
  const status = text ? { label: tr("copy.text_chat_d88c4d0"), tone: "off" as const } : STATUS[connection];
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full bg-sunken px-2.5 py-1 text-xs text-muted">
      <span
        aria-hidden
        className={cn(
          "size-2 rounded-full",
          status.tone === "live" && "bg-primary",
          status.tone === "wait" && "animate-pulse bg-ink/60",
          status.tone === "off" && "bg-line-strong",
        )}
      />
      {localize(status.label)}
    </span>
  );
}

function RoundButton({
  label,
  onClick,
  pressed,
  danger,
  children,
}: {
  label: string;
  onClick: () => void;
  pressed?: boolean;
  danger?: boolean;
  children: ReactNode;
}) {
  useLocale();
  return (
    <button
      type="button"
      aria-label={localize(label)}
      title={localize(label)}
      aria-pressed={pressed}
      onClick={onClick}
      className={cn(
        "flex size-14 items-center justify-center rounded-full border transition-colors [&_svg]:size-6",
        danger
          ? "border-transparent bg-danger text-white hover:opacity-90"
          : pressed
            ? "border-ink bg-ink text-canvas"
            : "border-line-strong bg-surface text-ink hover:bg-sunken",
      )}
    >
      {localize(children)}
    </button>
  );
}

function Intro({ text, onExample }: { text: boolean; onExample: (prompt: string) => void }) {
  useLocale();
  return (
    <div className="flex min-h-full flex-col justify-end gap-3 pb-2">
      <h3 className="text-2xl">{tr("copy.what_are_you_working_on_b1a2017")}</h3>
      <p className="max-w-sm text-muted">
        {text ? tr("copy.write_4a48932") : tr("copy.talk_4e6a710")} {tr("copy.in_the_language_you_re_most_comfortable_with_ada_38f4588")}</p>
      {text && (
        <ul className="mt-2 flex flex-col gap-2">
          {EXAMPLES.map((example) => (
            <li key={example}>
              <button
                type="button"
                onClick={() => onExample(example)}
                className="text-start text-sm text-muted underline decoration-line-strong underline-offset-4 hover:text-ink hover:decoration-ink"
              >
                {localize(example)}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export type PanelVariant = "dock" | "sheet" | "page";

/**
 * The whole conversation (voice and text) in a container-agnostic panel: it fills its
 * parent and has no dialog of its own. `sheet` draws its own header with a close button;
 * `dock` and `page` show a slim status row and leave the chrome to the host.
 * Closing or unmounting never ends a call: the controller owns it.
 */
export function ConversationPanel({
  variant,
  onClose,
  className,
}: {
  variant: PanelVariant;
  onClose?: () => void;
  className?: string;
}) {
  useLocale();
  const state = useVoiceStore();
  const info = useSystemInfo();
  const voiceAvailable = info.data?.features.voice ?? false;
  const [typing, setTyping] = useState(false);

  const phase = derivePhase(state);
  const textMode = state.mode === "text";
  const active = ACTIVE.includes(state.connection) && !textMode;
  const startable = !textMode && (phase === "idle" || phase === "ended" || phase === "failed");
  const runningTool = selectRunningTool(state);
  const caption = phase === "tool" && runningTool ? runningTool.label : CAPTION[phase];

  // Without voice in this deployment, open straight into typing.
  useEffect(() => {
    if (info.data && !voiceAvailable && state.mode === "voice" && !active) dispatch({ type: "mode", mode: "text" });
  }, [info.data, voiceAvailable, state.mode, active]);

  const lockHint =
    active && !ScreenWakeLock.supported && typeof matchMedia === "function" && matchMedia("(pointer: coarse)").matches;
  const newConversation = state.items.length > 0 && !active && (
    <IconButton label={tr("copy.start_a_new_conversation_d1d9a4c")} onClick={() => voice.newConversation()}>
      <RotateCcw className="size-5" aria-hidden />
    </IconButton>
  );

  return (
    <div className={cn("flex h-full min-h-0 flex-col bg-canvas", className)}>
      {variant === "sheet" ? (
        <header className="pt-safe border-b border-line">
          <div className="flex h-14 items-center gap-3 px-4">
            <h2 id="voice-title" className="text-lg">
              {tr("copy.adapt_2e26648")}</h2>
            <StatusPill connection={state.connection} text={localize(textMode)} />
            <div className="ms-auto flex items-center gap-1">
              {localize(newConversation)}
              {onClose && (
                <IconButton label={active ? tr("copy.minimise_the_conversation_keeps_going_09f2a81") : tr("copy.close_bbfa773")} onClick={onClose}>
                  {active ? <Minimize2 className="size-5" aria-hidden /> : <X className="size-5" aria-hidden />}
                </IconButton>
              )}
            </div>
          </div>
        </header>
      ) : (
        <div className="flex min-h-12 items-center gap-2 border-b border-line px-4 py-1.5">
          <StatusPill connection={state.connection} text={localize(textMode)} />
          <div className="ms-auto">{localize(newConversation)}</div>
        </div>
      )}

      <Transcript
        items={state.items}
        onNavigate={variant === "sheet" ? onClose : undefined}
        empty={<Intro text={textMode} onExample={(prompt) => void voice.sendText(prompt)} />}
      />

      {state.problem && (
        <ProblemBanner
          problem={state.problem}
          mode={state.mode}
          onRetry={() => void voice.startVoice()}
          onType={() => voice.useText()}
          onDismiss={() => dispatch({ type: "problem", problem: null })}
        />
      )}

      {textMode ? (
        <div className="border-t border-line bg-canvas px-4 pt-3 pb-[calc(env(safe-area-inset-bottom)+0.75rem)]">
          {state.responding && (
            <p className="mb-2 flex items-center gap-2 text-sm text-muted" aria-live="polite">
              <Spinner className="size-4" />
              {localize(runningTool?.label ?? tr("copy.thinking_d08d8da"))}
            </p>
          )}
          <Composer
            onSend={(text) => void voice.sendText(text)}
            disabled={state.responding}
            placeholder={tr("copy.ask_about_visas_housing_your_plan_4d993a6")}
            autoFocus={variant !== "page"}
          />
          {voiceAvailable && (
            <button
              type="button"
              onClick={() => void voice.startVoice()}
              className="mt-2 inline-flex h-10 items-center gap-2 rounded-md px-2 text-sm font-medium text-primary hover:bg-sunken"
            >
              <Mic className="size-4" aria-hidden />
              {tr("copy.talk_instead_39fee0b")}</button>
          )}
        </div>
      ) : (
        <div className="flex flex-col items-center gap-1 px-4 pt-2 pb-[calc(env(safe-area-inset-bottom)+1rem)]">
          {typing && active && (
            <div className="w-full pb-2">
              <Composer onSend={(text) => void voice.sendText(text)} placeholder={tr("copy.type_instead_of_speaking_3eb5d21")} autoFocus />
            </div>
          )}
          <VoiceOrb
            phase={phase}
            levels={readLevels}
            onStart={startable ? () => void voice.startVoice() : undefined}
            label={startable ? tr("copy.start_talking_to_adapt_c480f9b") : caption}
          />
          <p className="min-h-6 text-center text-sm text-muted" aria-live="polite">
            {localize(caption)}
          </p>
          {active ? (
            <div className="mt-2 flex items-center justify-center gap-5">
              <RoundButton
                label={state.muted ? tr("copy.unmute_microphone_da15692") : tr("copy.mute_microphone_f83cc99")}
                pressed={state.muted}
                onClick={() => voice.toggleMute()}
              >
                {state.muted ? <MicOff aria-hidden /> : <Mic aria-hidden />}
              </RoundButton>
              <RoundButton label={tr("copy.type_a_message_95f90de")} pressed={typing} onClick={() => setTyping((v) => !v)}>
                <Keyboard aria-hidden />
              </RoundButton>
              <RoundButton label={tr("copy.end_conversation_4751bc7")} danger onClick={() => voice.endVoice()}>
                <PhoneOff aria-hidden />
              </RoundButton>
            </div>
          ) : (
            <button
              type="button"
              onClick={() => voice.useText()}
              className="mt-1 inline-flex h-11 items-center gap-2 rounded-md px-3 text-sm font-medium text-ink hover:bg-sunken"
            >
              <Keyboard className="size-4" aria-hidden />
              {tr("copy.type_instead_78a8fc4")}</button>
          )}
          {lockHint && <p className="mt-2 text-xs text-subtle">{tr("copy.keep_adapt_open_while_you_talk_9e224cb")}</p>}
        </div>
      )}
    </div>
  );
}

export default ConversationPanel;
