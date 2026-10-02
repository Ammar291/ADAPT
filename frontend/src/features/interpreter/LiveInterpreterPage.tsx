import { currentLocale, tr, localize, useLocale } from "@/i18n";
import { useEffect, useMemo, useState, useSyncExternalStore } from "react";
import { Link, useSearchParams } from "react-router";
import { ArrowLeft, ArrowLeftRight, Captions, Headphones, Languages, Mic, MicOff, Pause, Play, RotateCcw, Square, Volume2 } from "lucide-react";
import { LanguagePicker, LanguageSelector } from "@/i18n/LanguageSelector";
import { getLanguage } from "@/i18n/registry";
import { config } from "@/lib/config";
import { BrandMark } from "@/app/layout/BrandMark";
import { demoApi, interpreterApi } from "./api";
import { InterpreterController, type StartOptions } from "./controller";
import { direction, pairFromSearch, pairProblem, swapPair } from "./languages";
import type { Capabilities, InterpreterState, Language, Pair, Speaker, Transcript } from "./types";
import "./interpreter.css";
import { TextFallback } from "./TextFallback";

const stateLabels: Record<InterpreterState, string> = { idle: tr("copy.idle_cc1ebdd", { lng: "en" }), connecting: tr("copy.connecting_c1f3b71", { lng: "en" }), listening: tr("copy.listening_dc35348", { lng: "en" }), translating: tr("copy.translating_b8faf22", { lng: "en" }), speaking: tr("copy.speaking_a771fe6", { lng: "en" }), paused: tr("copy.paused_c7dfb6f", { lng: "en" }), reconnecting: tr("copy.reconnecting_9d80f91", { lng: "en" }), stopped: tr("copy.stopped_51e9111", { lng: "en" }), error: tr("copy.error_7f2f6a1", { lng: "en" }) };
const stateHints: Record<InterpreterState, string> = { idle: tr("copy.two_people_two_languages_one_conversation_e57446a", { lng: "en" }), connecting: tr("copy.preparing_your_microphone_and_translation_sessio_3b43a9f", { lng: "en" }), listening: tr("copy.choose_who_is_speaking_then_speak_naturally_fea6b73", { lng: "en" }), translating: tr("copy.translating_speech_subtitles_appear_as_they_arri_f239d58", { lng: "en" }), speaking: tr("copy.playing_the_translated_speech_3e0828b", { lng: "en" }), paused: tr("copy.microphones_are_paused_resume_when_you_are_ready_b7f19c8", { lng: "en" }), reconnecting: tr("copy.restoring_the_connection_with_fresh_session_cred_00e762f", { lng: "en" }), stopped: tr("copy.conversation_ended_your_microphone_is_off_40becce", { lng: "en" }), error: tr("copy.the_interpreter_needs_your_attention_519ebe3", { lng: "en" }) };

export function InterpreterTranscript({ transcript, source, target, subtitles }: { transcript: Transcript; source: Language; target: Language; subtitles: boolean }) {
  useLocale();
  return <div className="interp-transcript">{localize(subtitles ? <>
    <div className="interp-original"><div className="interp-text-label">{tr("copy.original_5568914")}<span>{localize(source.name)}</span></div><p lang={transcript.original ? source.code : currentLocale()} dir={transcript.original ? source.rtl ? "rtl" : "ltr" : undefined} className={!transcript.original ? "interp-placeholder" : undefined}>{transcript.original || tr("copy.your_speech_will_appear_here_dd7f183")}</p></div>
    <div className="interp-translation"><div className="interp-text-label">{tr("copy.translation_10ecb0e")}<span>{localize(target.name)}</span></div><p lang={transcript.translation ? target.code : currentLocale()} dir={transcript.translation ? target.rtl ? "rtl" : "ltr" : undefined} className={!transcript.translation ? "interp-placeholder" : undefined}>{transcript.translation || tr("copy.the_translation_will_appear_here_02dfe11")}</p></div>
  </> : <div className="interp-hidden"><Captions aria-hidden />{tr("copy.subtitles_are_hidden_translated_audio_stays_on_280b8e3")}</div>)}</div>;
}

export default function InterpreterPage() {
  const uiLocale = useLocale();
  const [params, setParams] = useSearchParams();
  const demo = config.demoMode || params.get("demo") === "1";
  const api = demo ? demoApi : interpreterApi;
  const controller = useMemo(() => new InterpreterController(api), [api]);
  const snapshot = useSyncExternalStore(controller.subscribe, controller.getSnapshot);
  const [cap, setCap] = useState<Capabilities | null>(null);
  const [capError, setCapError] = useState<string | null>(null);
  const [subtitles, setSubtitles] = useState(true);
  const [headphones, setHeadphones] = useState(false);
  const [recorded, setRecorded] = useState(false);
  const [separate, setSeparate] = useState(false);
  const [devices, setDevices] = useState<MediaDeviceInfo[]>([]);
  const [deviceA, setDeviceA] = useState(""); const [deviceB, setDeviceB] = useState("");
  const pair = pairFromSearch(params.toString());
  const active = !["idle", "stopped", "error"].includes(snapshot.state);
  const busy = ["connecting", "reconnecting"].includes(snapshot.state);
  const languages = useMemo(() => (cap?.languages ?? []).map((item) => {
    const language = getLanguage(item.code);
    return { ...item, name: language ? language.nativeName === language.englishName ? language.englishName : `${language.nativeName} · ${language.englishName}` : item.name, rtl: language?.direction === "rtl" || item.rtl };
  }), [cap]);
  const lookup = (code: string): Language => languages.find((lang) => lang.code === code) ?? { code, name: code, rtl: false, input: false, output: false, fallback: false };
  const problem = cap ? pairProblem(pair, cap) : null;
  const fallbackPair = [pair.source, pair.target].some((code) => !lookup(code).output);
  const options = (): StartOptions => ({ demo, headphones, recorded, ...(separate ? { devices: [deviceA, deviceB] as [string, string] } : {}) });
  const refreshDevices = async () => { try { setDevices((await navigator.mediaDevices?.enumerateDevices() ?? []).filter((device) => device.kind === "audioinput" && device.deviceId && device.deviceId !== "default" && device.deviceId !== "communications")); } catch { /* Input selection is optional. */ } };
  useEffect(() => {
    let live = true;
    void api.capabilities().then((value) => { if (live) { setCap(value); setCapError(null); } }).catch(() => { if (live) setCapError(tr("copy.could_not_load_translation_capabilities_check_yo_e019dd5", { lng: "en" })); });
    return () => { live = false; controller.end(false); };
  }, [api, controller]);
  useEffect(() => {
    const hidden = () => { if (document.hidden) controller.pause(); };
    const online = () => { if (controller.getSnapshot().state === "reconnecting") void controller.reconnect(); };
    const leave = () => controller.end();
    document.addEventListener("visibilitychange", hidden); window.addEventListener("online", online); window.addEventListener("pagehide", leave);
    return () => { document.removeEventListener("visibilitychange", hidden); window.removeEventListener("online", online); window.removeEventListener("pagehide", leave); };
  }, [controller]);
  useEffect(() => { document.title = `ADAPT · ${tr("interpreter.title")}`; }, [uiLocale]);
  const changePair = (value: Pair) => { const next = new URLSearchParams(params); next.set("source", value.source); next.set("target", value.target); setParams(next, { replace: true }); };
  const swap = () => { const next = swapPair(pair); const running = active; controller.end(); changePair(next); if (running && cap && !pairProblem(next, cap)) void controller.start(next, options()); };
  const start = async () => { await controller.start(pair, options()); await refreshDevices(); };
  const stateHint = snapshot.mode === "demo" && snapshot.state === "listening" ? tr("copy.choose_a_speaker_then_play_a_scripted_sample_mic_97e5203") : snapshot.muted ? tr("copy.microphone_muted_unmute_to_continue_speaking_34f4744") : stateHints[snapshot.state];

  return <div className="interpreter-page">
    <header className="interp-header"><Link to={config.demoMode ? "/demo/founder-arrival" : "/home"} className="interp-back" aria-label={tr("copy.back_to_adapt_62cc500")}><ArrowLeft size={20} aria-hidden /></Link><BrandMark className="size-8" /><div><div className="interp-wordmark">{tr("copy.adapt_09d9776")}<span>{tr("copy.interpreter_cc0078a")}</span></div><p>{tr("copy.live_human_to_human_translation_7358a21")}</p></div><span className="interp-disclosure">{tr("copy.ai_generated_translation_547dd55")}</span>{demo ? <LanguagePicker className="interp-locale" /> : <LanguageSelector className="interp-locale" />}</header>
    <main className="interp-main" id="interpreter-main">
      <div className="interp-intro"><span className="interp-eyebrow"><Languages size={15} aria-hidden /> {tr("copy.a_conversation_without_the_language_barrier_1f71c91")}</span><h1>{tr("copy.understand_each_other_58ad7b0")}</h1><p>{tr("copy.speak_in_your_language_hear_theirs_in_yours_2995767")}</p></div>
      <section className="interp-pair" aria-label={tr("copy.language_pair_3392baa")}>
        <label>{tr("copy.language_a_fb2fa05")}<select aria-label={tr("copy.language_a_fb2fa05")} value={pair.source} disabled={active || !cap} onChange={(e) => changePair({ ...pair, source: e.target.value })}>{localize(!languages.some((l) => l.code === pair.source) && <option value={pair.source}>{localize(pair.source)}</option>)}{localize(languages.map((lang) => <option key={lang.code} value={lang.code} disabled={!lang.input || !lang.output && !cap?.fallback_enabled}>{localize(lang.name)}{localize(!lang.output ? tr("copy.recorded_output_bbfa05d") : "")}</option>))}</select></label>
        <button type="button" className="interp-swap" aria-label={tr("copy.swap_languages_efa6cab")} onClick={swap} disabled={busy || !cap}><ArrowLeftRight size={22} aria-hidden /></button>
        <label>{tr("copy.language_b_9a69090")}<select aria-label={tr("copy.language_b_9a69090")} value={pair.target} disabled={active || !cap} onChange={(e) => changePair({ ...pair, target: e.target.value })}>{localize(!languages.some((l) => l.code === pair.target) && <option value={pair.target}>{localize(pair.target)}</option>)}{localize(languages.map((lang) => <option key={lang.code} value={lang.code} disabled={!lang.input || !lang.output && !cap?.fallback_enabled}>{localize(lang.name)}{localize(!lang.output ? tr("copy.recorded_output_bbfa05d") : "")}</option>))}</select></label>
      </section>
      {localize(cap && fallbackPair && !problem && !demo && <p className="interp-support"><strong>{tr("copy.arabic_output_uses_recorded_translation_62ffdb9")}</strong> {tr("copy.speak_a_short_phrase_then_tap_translate_arabic_e_ec31565")}<a href={cap.source} target="_blank" rel="noreferrer">{tr("copy.language_support_e794492")}</a></p>)}
      {localize((demo || snapshot.mode === "demo" || cap?.mode === "demo") && <p className="interp-demo"><strong>{tr("copy.demo_038bc41")}</strong> {tr("copy.scripted_samples_only_no_microphone_capture_or_l_8f22c63")}</p>)}
      {localize((problem || capError || snapshot.error) && <div className="interp-error" role="alert">{localize(problem || capError || snapshot.error)}{localize(!demo && <a href={`/interpreter?source=${encodeURIComponent(pair.source)}&target=${encodeURIComponent(pair.target)}&demo=1`}>{tr("copy.open_safe_demo_8099be0")}</a>)}</div>)}
      {localize(snapshot.notice && snapshot.mode !== "demo" && <p className="interp-notice" role="status">{localize(snapshot.notice)}</p>)}
      {!demo && (snapshot.error || snapshot.notice || capError) && <TextFallback pair={pair} api={api} onUse={() => controller.end(false)} />}
      <div className="interp-status" role="status" aria-live="polite"><span className={`interp-state interp-state-${snapshot.state}`}><span className="interp-dot" />{localize(stateLabels[snapshot.state])}{localize(snapshot.muted ? tr("copy.muted_8dcd3dc") : "")}</span><span>{localize(stateHint)}</span></div>
      {localize(!active && <div className="interp-start-area"><button className="interp-start" onClick={() => void start()} disabled={!cap || !!problem || cap.mode === "unavailable" || separate && (!deviceA || !deviceB || deviceA === deviceB)}><Mic size={21} aria-hidden />{localize(demo || cap?.mode === "demo" ? tr("copy.start_demo_interpreter_2a8b5e4") : tr("copy.start_interpreter_7145efc"))}</button><p>{localize(demo || cap?.mode === "demo" ? tr("copy.demo_samples_use_no_microphone_e4e60e3") : tr("copy.microphone_access_is_requested_only_when_you_sta_325dd63"))}</p></div>)}
      <section className="interp-speakers" aria-label={tr("copy.participants_cd56e08")}>{localize((["a", "b"] as Speaker[]).map((speaker) => {
        const d = direction(pair, speaker); const source = lookup(d.source); const target = lookup(d.target); const selected = snapshot.active === speaker;
        return <article key={speaker} className={`interp-speaker ${selected ? "interp-selected" : ""}`} aria-label={localize(speaker === "a" ? tr("copy.you_905cb32") : tr("copy.other_person_677f338"))}>
          <header><div className={`interp-avatar interp-avatar-${speaker}`}>{localize(speaker === "a" ? tr("copy.a_6dcd4ce") : tr("copy.b_ae4f281"))}</div><div><h2>{localize(speaker === "a" ? tr("copy.you_af319ea") : tr("copy.other_person_603c6a6"))}</h2><span>{localize(source.name)}</span></div><span className="interp-direction" dir="ltr">{localize(source.code.toUpperCase())} <span>{tr("copy.text_213edd2")}</span> {localize(target.code.toUpperCase())}</span></header>
          <InterpreterTranscript transcript={snapshot.transcripts[speaker]} source={source} target={target} subtitles={subtitles} />
          <footer><button className="interp-speaker-select" aria-pressed={selected} disabled={!active || busy || snapshot.recording} onClick={() => controller.selectSpeaker(speaker)}><Mic size={17} aria-hidden />{localize(selected && active ? tr("copy.selected_speaker_15e0840") : speaker === "a" ? tr("copy.you_speak_d340b7a") : tr("copy.other_person_speaks_6f23a15"))}</button><button className="interp-replay" aria-label={localize(tr("copy.replay_latest_translation_for_v0_3525649", { v0: speaker === "a" ? tr("copy.you_905cb32") : tr("copy.other_person_677f338") }))} title={tr("copy.available_after_translated_audio_finishes_if_thi_f09f6a8")} disabled={!snapshot.replayable[speaker] || snapshot.recording || busy} onClick={() => void controller.replay(speaker)}><Volume2 size={18} aria-hidden />{tr("copy.replay_c0f85d6")}</button></footer>
        </article>;
      }))}</section>
      {localize(active && !busy && <div className="interp-mic-area"><button className={`interp-mic ${snapshot.recording ? "interp-recording" : ""}`} aria-label={localize(snapshot.mode === "demo" ? tr("copy.play_sample_for_selected_speaker_08bf342") : snapshot.transports[snapshot.active] === "recorded" ? snapshot.recording ? tr("copy.translate_recording_bf4f183") : tr("copy.record_selected_speaker_95a2f71") : snapshot.muted ? tr("copy.unmute_microphone_da15692") : tr("copy.mute_microphone_f83cc99"))} disabled={snapshot.paused || snapshot.state === "speaking" || snapshot.state === "translating" && snapshot.transports[snapshot.active] === "recorded"} onClick={() => { if (snapshot.mode === "demo") controller.sample(); else if (snapshot.transports[snapshot.active] === "recorded") void controller.record(); else controller.mute(); }} style={{ boxShadow: `0 0 0 ${8 + Math.min(15, snapshot.level * 60)}px var(--teal-tint)` }}>{localize(snapshot.recording ? <Square size={27} aria-hidden /> : snapshot.muted ? <MicOff size={30} aria-hidden /> : <Mic size={30} aria-hidden />)}</button><div><strong>{localize(snapshot.active === "a" ? tr("copy.you_905cb32") : tr("copy.other_person_677f338"))} {tr("copy.text_ddb36e6")}{localize(lookup(direction(pair, snapshot.active).source).name)}</strong><span>{localize(snapshot.mode === "demo" ? tr("copy.tap_for_a_scripted_sample_35e52f7") : snapshot.transports[snapshot.active] === "recorded" ? snapshot.recording ? tr("copy.tap_to_translate_up_to_25_seconds_d54337f") : tr("copy.tap_to_record_a_short_phrase_08a97b3") : snapshot.muted ? tr("copy.tap_to_unmute_71092c7") : tr("copy.microphone_on_tap_to_mute_7a618e6"))}</span></div></div>)}
      {localize(snapshot.playbackBlocked && <button className="interp-enable" onClick={() => void controller.enableAudio()}><Volume2 size={18} aria-hidden />{tr("copy.enable_audio_8e623ec")}</button>)}
      <div className="interp-controls" aria-label={tr("copy.interpreter_controls_916e1f1")}><button disabled={!active || busy} onClick={() => snapshot.paused ? void controller.resume() : controller.pause()}>{localize(snapshot.paused ? <Play size={18} aria-hidden /> : <Pause size={18} aria-hidden />)}{localize(snapshot.paused ? tr("copy.resume_b3bd0b5") : tr("copy.pause_781961b"))}</button><button disabled={!active || busy} aria-pressed={snapshot.muted} onClick={() => controller.mute()}>{localize(snapshot.muted ? <MicOff size={18} aria-hidden /> : <Mic size={18} aria-hidden />)}{localize(snapshot.muted ? tr("copy.unmute_7044c31") : tr("copy.mute_0f09734"))}</button><button disabled={!cap || busy} onClick={swap}><ArrowLeftRight size={18} aria-hidden />{tr("copy.swap_210dd62")}</button><button aria-pressed={subtitles} onClick={() => setSubtitles(!subtitles)}><Captions size={18} aria-hidden />{subtitles ? tr("interpreter.subtitlesOn") : tr("interpreter.subtitlesOff")}</button><button className="interp-end" disabled={!active} onClick={() => controller.end()}><Square size={16} aria-hidden />{tr("interpreter.stop")}</button></div>
      <details className="interp-settings"><summary>{tr("copy.audio_settings_connection_help_41150ae")}</summary><div>
        <label><input type="checkbox" checked={headphones} disabled={active} onChange={(e) => setHeadphones(e.target.checked)} /><Headphones size={17} aria-hidden /><span>{tr("copy.using_headphones_allow_continuous_speech_during__31639f3")}</span></label>
        <p>{tr("copy.on_speakers_microphone_inputs_pause_while_transl_bf0b041")}</p>
        <label><input type="checkbox" checked={recorded} disabled={active || !cap?.fallback_enabled || demo} onChange={(e) => setRecorded(e.target.checked)} /><RotateCcw size={17} aria-hidden /><span>{tr("copy.use_recorded_translation_for_both_directions_if__c1beae3")}</span></label>
        <label><input type="checkbox" checked={separate} disabled={active || demo} onChange={(e) => { setSeparate(e.target.checked); void refreshDevices(); }} /><span>{tr("copy.use_two_separate_microphone_devices_faa52fb")}</span></label>
        {localize(separate && <div className="interp-device-selects"><label>{tr("copy.speaker_a_input_0400ff6")}<select value={deviceA} disabled={active} onChange={(e) => setDeviceA(e.target.value)}><option value="">{tr("copy.choose_microphone_a_5fb4afc")}</option>{localize(devices.map((d, i) => <option key={d.deviceId} value={d.deviceId}>{localize(d.label || tr("interpreter.microphone", { number: i + 1 }))}</option>))}</select></label><label>{tr("copy.speaker_b_input_175fd13")}<select value={deviceB} disabled={active} onChange={(e) => setDeviceB(e.target.value)}><option value="">{tr("copy.choose_microphone_b_a5b8f48")}</option>{localize(devices.map((d, i) => <option key={d.deviceId} value={d.deviceId}>{localize(d.label || tr("copy.microphone_v0_304078b", { v0: i + 1 }))}</option>))}</select></label><p>{tr("copy.start_once_with_a_shared_microphone_to_grant_acc_3df0f8b")}</p></div>)}
        <p>{tr("copy.use_https_or_localhost_in_chrome_android_safari__edca1d0")}</p>
      </div></details>
      <p className="interp-footnote">{tr("copy.ai_generated_translation_2a577dc")}<span>{tr("copy.text_1fdf0d9")}</span> {tr("copy.subtitles_and_replay_audio_stay_in_this_page_s_m_3f9c447")}</p>
    </main>
  </div>;
}
