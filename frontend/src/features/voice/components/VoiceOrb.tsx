import { localize, useLocale } from "@/i18n";
import { Mic, MicOff, WifiOff } from "lucide-react";
import { useEffect, useRef, type ReactNode, type RefObject } from "react";
import type { Phase } from "../conversation";

const ICON: Partial<Record<Phase, ReactNode>> = {
  muted: <MicOff aria-hidden />,
  offline: <WifiOff aria-hidden />,
  failed: <MicOff aria-hidden />,
};

/**
 * The orb. Audio levels are written straight to CSS variables on animation frames (not
 * React state), so it stays smooth without re-rendering the sheet 60 times a second.
 */
export function VoiceOrb({
  phase,
  levels,
  onStart,
  label,
}: {
  phase: Phase;
  levels: () => { input: number; output: number };
  onStart?: () => void;
  label: string;
}) {
  useLocale();
  const ref = useRef<HTMLElement>(null);
  const live = phase === "listening" || phase === "user_speaking" || phase === "speaking";

  useEffect(() => {
    const element = ref.current;
    if (!element || !live || matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    let frame = 0;
    const tick = () => {
      const { input, output } = levels();
      element.style.setProperty("--in", input.toFixed(3));
      element.style.setProperty("--out", output.toFixed(3));
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => {
      cancelAnimationFrame(frame);
      element.style.setProperty("--in", "0");
      element.style.setProperty("--out", "0");
    };
  }, [live, levels]);

  const parts = (
    <>
      <span className="voice-orb-ring" data-ring="3" aria-hidden />
      <span className="voice-orb-ring" data-ring="2" aria-hidden />
      <span className="voice-orb-ring" data-ring="1" aria-hidden />
      <span className="voice-orb-orbit" aria-hidden />
      <span className="voice-orb-core">{ICON[phase] ?? <Mic aria-hidden />}</span>
    </>
  );

  if (onStart) {
    return (
      <button
        ref={ref as RefObject<HTMLButtonElement>}
        type="button"
        className="voice-orb"
        data-phase={phase}
        onClick={onStart}
        aria-label={localize(label)}
      >
        {localize(parts)}
      </button>
    );
  }
  return (
    <div ref={ref as RefObject<HTMLDivElement>} className="voice-orb" data-phase={phase} role="img" aria-label={localize(label)}>
      {localize(parts)}
    </div>
  );
}
