import { tr } from "@/i18n";
import { useCallback, useEffect, useRef, useState } from "react";

interface RecognitionResult {
  isFinal: boolean;
  0: { transcript: string };
}
interface Recognition {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  onresult: ((event: { resultIndex: number; results: ArrayLike<RecognitionResult> }) => void) | null;
  onerror: ((event: { error: string }) => void) | null;
  onend: (() => void) | null;
  start(): void;
  stop(): void;
  abort(): void;
}
type RecognitionCtor = new () => Recognition;

function ctor(): RecognitionCtor | null {
  if (typeof window === "undefined") return null;
  const w = window as unknown as { SpeechRecognition?: RecognitionCtor; webkitSpeechRecognition?: RecognitionCtor };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

/**
 * Local dictation into a text field, using the browser's speech recognition. Nothing is
 * recorded by ADAPT; the browser transcribes. Unsupported browsers simply don't show it.
 */
export function useDictation(onText: (finalText: string) => void) {
  const [listening, setListening] = useState(false);
  const [interim, setInterim] = useState("");
  const [error, setError] = useState<string | null>(null);
  const recognition = useRef<Recognition | null>(null);
  const callback = useRef(onText);
  callback.current = onText;
  const supported = ctor() !== null;

  const reset = useCallback(() => {
    const current = recognition.current;
    if (current) { current.onresult = null; current.onerror = null; current.onend = null; current.abort(); }
    recognition.current = null;
    setListening(false); setInterim(""); setError(null);
  }, []);
  useEffect(() => () => {
    const current = recognition.current;
    if (current) { current.onresult = null; current.onerror = null; current.onend = null; current.abort(); }
  }, []);

  const stop = useCallback(() => {
    recognition.current?.stop();
  }, []);

  const start = useCallback(() => {
    const Ctor = ctor();
    if (!Ctor) return;
    const previous = recognition.current;
    if (previous) { previous.onresult = null; previous.onerror = null; previous.onend = null; previous.abort(); }
    setError(null);
    const r = new Ctor();
    r.lang = typeof navigator !== "undefined" ? navigator.language : "en";
    r.continuous = true;
    r.interimResults = true;
    r.onresult = (event) => {
      let pending = "";
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const result = event.results[i]!;
        if (result.isFinal) callback.current(result[0].transcript.trim());
        else pending += result[0].transcript;
      }
      setInterim(pending);
    };
    r.onerror = (event) => {
      if (event.error === "not-allowed" || event.error === "service-not-allowed") {
        setError(tr("copy.microphone_access_is_blocked_allow_it_in_your_br_73aef1a"));
      } else if (event.error !== "no-speech" && event.error !== "aborted") {
        setError(tr("copy.dictation_stopped_try_again_or_type_instead_798b3c4"));
      }
    };
    r.onend = () => {
      setListening(false);
      setInterim("");
    };
    recognition.current = r;
    try {
      r.start();
      setListening(true);
    } catch {
      setListening(false);
      setError(tr("copy.dictation_couldn_t_start_try_again_or_type_inste_a0cada8"));
    }
  }, []);

  return { supported, listening, interim, error, start, stop, reset };
}
