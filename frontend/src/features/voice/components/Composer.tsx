import { tr, localize, useLocale } from "@/i18n";
import { SendHorizontal } from "lucide-react";
import { useId, useRef, useState } from "react";
import { cn } from "@/lib/cn";

/** Typed input for text mode, or for typing mid-call. Enter sends; Shift+Enter adds a line. */
export function Composer({
  onSend,
  disabled,
  placeholder,
  autoFocus,
}: {
  onSend: (text: string) => void;
  disabled?: boolean;
  placeholder: string;
  autoFocus?: boolean;
}) {
  useLocale();
  const [text, setText] = useState("");
  const ref = useRef<HTMLTextAreaElement>(null);
  const id = useId();

  const submit = () => {
    const value = text.trim();
    if (!value || disabled) return;
    onSend(value);
    setText("");
    ref.current?.focus();
  };

  return (
    <form
      className="flex items-end gap-2 rounded-xl border border-line-strong bg-surface p-2 focus-within:border-primary"
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
    >
      <label htmlFor={id} className="sr-only">
        {tr("copy.message_adapt_f7d3189")}</label>
      <textarea
        id={id}
        ref={ref}
        value={text}
        rows={1}
        dir="auto"
        autoFocus={autoFocus}
        placeholder={localize(placeholder)}
        enterKeyHint="send"
        maxLength={4000}
        onChange={(event) => {
          setText(event.target.value);
          const el = event.target;
          el.style.height = "auto";
          el.style.height = `${Math.min(el.scrollHeight, 132)}px`;
        }}
        onKeyDown={(event) => {
          if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
            event.preventDefault();
            submit();
          }
        }}
        className="max-h-[132px] min-h-10 flex-1 resize-none bg-transparent px-2 py-2 text-base placeholder:text-subtle focus:outline-none"
      />
      <button
        type="submit"
        aria-label={tr("copy.send_9bc2575")}
        disabled={disabled || !text.trim()}
        className={cn(
          "flex size-11 shrink-0 items-center justify-center rounded-lg transition-colors",
          "bg-primary text-on-primary hover:bg-primary-strong disabled:bg-sunken disabled:text-subtle",
        )}
      >
        <SendHorizontal className="flip-rtl size-5" aria-hidden />
      </button>
    </form>
  );
}
