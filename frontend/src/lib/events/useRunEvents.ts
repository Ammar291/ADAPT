import { useEffect, useReducer, useState } from "react";
import type { RunEvent, StreamState } from "@/domain/runs";
import { useServices } from "@/services/context";
import { initialRunView, reduceRunEvent, type RunView } from "./runEvents";

type Action = { type: "event"; event: RunEvent } | { type: "reset"; runId: string | null };

function reducer(state: RunView, action: Action): RunView {
  return action.type === "reset" ? initialRunView(action.runId) : reduceRunEvent(state, action.event);
}

/**
 * Subscribe to a run's progress. The run's history is replayed, then live events stream in
 * (SSE with Last-Event-ID replay for live runs), so reconnecting never loses events.
 */
export function useRunEvents(runId: string | null): { view: RunView; stream: StreamState } {
  const services = useServices();
  const [view, dispatch] = useReducer(reducer, runId, initialRunView);
  const [stream, setStream] = useState<StreamState>("idle");

  useEffect(() => {
    dispatch({ type: "reset", runId });
    if (!runId) {
      setStream("idle");
      return;
    }
    return services.runs.subscribe(runId, {
      onEvent: (event) => dispatch({ type: "event", event }),
      onState: setStream,
    });
  }, [runId, services]);

  return { view, stream };
}
