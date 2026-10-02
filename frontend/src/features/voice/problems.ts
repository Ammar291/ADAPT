import { tr } from "@/i18n";
import type { Problem, ProblemCode } from "./conversation";

const COPY: Record<ProblemCode, Omit<Problem, "code">> = {
  mic_denied: {
    title: tr("copy.adapt_can_t_hear_you_a7884dd", { lng: "en" }),
    detail: tr("copy.microphone_access_is_blocked_for_this_site_allow_b1de076", { lng: "en" }),
    canRetry: true,
  },
  mic_missing: {
    title: tr("copy.no_microphone_found_b47abe7", { lng: "en" }),
    detail: tr("copy.connect_a_microphone_or_headset_and_try_again_or_3253daf", { lng: "en" }),
    canRetry: true,
  },
  mic_busy: {
    title: tr("copy.your_microphone_is_in_use_80a9b74", { lng: "en" }),
    detail: tr("copy.another_app_is_using_the_microphone_close_it_and_fea2f9d", { lng: "en" }),
    canRetry: true,
  },
  insecure_context: {
    title: tr("copy.voice_needs_a_secure_connection_c29fbb2", { lng: "en" }),
    detail: tr("copy.open_adapt_over_https_to_talk_you_can_type_here__0446e5f", { lng: "en" }),
    canRetry: false,
  },
  unsupported: {
    title: tr("copy.this_browser_can_t_do_voice_c3a5ebf", { lng: "en" }),
    detail: tr("copy.talking_needs_a_recent_chrome_safari_edge_or_fir_16d4fb9", { lng: "en" }),
    canRetry: false,
  },
  voice_unavailable: {
    title: tr("copy.voice_isn_t_available_right_now_0688c1a", { lng: "en" }),
    detail: tr("copy.you_can_type_instead_adapt_uses_the_same_tools_e_24b47ef", { lng: "en" }),
    canRetry: false,
  },
  connect_timeout: {
    title: tr("copy.voice_took_too_long_to_connect_5305953", { lng: "en" }),
    detail: tr("copy.check_your_connection_and_try_again_or_type_inst_d1f53e7", { lng: "en" }),
    canRetry: true,
  },
  connect_failed: {
    title: tr("copy.voice_couldn_t_connect_e7a1307", { lng: "en" }),
    detail: tr("copy.try_again_in_a_moment_or_type_instead_6bcf084", { lng: "en" }),
    canRetry: true,
  },
  connection_lost: {
    title: tr("copy.the_voice_connection_dropped_67fafe9", { lng: "en" }),
    detail: tr("copy.adapt_couldn_t_reconnect_your_conversation_is_ke_2e98934", { lng: "en" }),
    canRetry: true,
  },
  session_expired: {
    title: tr("copy.your_session_has_expired_d2cc219", { lng: "en" }),
    detail: tr("copy.reload_adapt_to_continue_94e1ba4", { lng: "en" }),
    canRetry: false,
  },
  rate_limited: {
    title: tr("copy.adapt_is_busy_4ffec1b", { lng: "en" }),
    detail: tr("copy.wait_a_moment_and_try_again_or_type_instead_d45f0a7", { lng: "en" }),
    canRetry: true,
  },
  assistant_error: {
    title: tr("copy.adapt_couldn_t_answer_dc28ee2", { lng: "en" }),
    detail: tr("copy.send_your_message_again_if_it_keeps_happening_re_8c4eb10", { lng: "en" }),
    canRetry: false,
  },
};

export function problem(code: ProblemCode, detail?: string | null): Problem {
  const copy = COPY[code];
  return { code, ...copy, detail: detail || copy.detail };
}
