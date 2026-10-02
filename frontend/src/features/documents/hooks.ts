/**
 * Feature-local data hooks. `useDocument` fills the gap left by the shared hooks: the live
 * list endpoint returns metadata only, so a document's fields are fetched when it's opened.
 */
import { useQuery } from "@tanstack/react-query";
import { useCallback, useEffect, useLayoutEffect, useMemo, useState } from "react";
import type { DocumentStatus } from "@/domain/documents";
import { useActiveJourney } from "@/lib/api/hooks";
import { queryKeys } from "@/lib/api/queryKeys";
import { useMediaQuery } from "@/lib/hooks/useMediaQuery";
import { useServices } from "@/services/context";
import { humanizeNodeKey } from "./lib/documents";

const BUSY: ReadonlySet<DocumentStatus> = new Set(["uploaded", "processing"]);

/**
 * One document with its extracted fields. Kept in memory only (TanStack Query), refetched
 * while it's being read and whenever the list reports a different status.
 */
export function useDocument(id: string | null, listStatus: DocumentStatus | undefined) {
  const { documents } = useServices();
  const query = useQuery({
    queryKey: queryKeys.private.document(id ?? ""),
    queryFn: ({ signal }) => documents.get(id!, signal),
    enabled: Boolean(id),
    refetchInterval: (q) => (q.state.data && BUSY.has(q.state.data.status) ? 2_500 : false),
  });
  const { refetch } = query;
  const loadedStatus = query.data?.status;
  useEffect(() => {
    if (id && listStatus && loadedStatus && listStatus !== loadedStatus) void refetch();
  }, [id, listStatus, loadedStatus, refetch]);
  return query;
}

/** Journey step titles by key, falling back to readable words when the plan isn't loaded. */
export function useNodeTitles(): (key: string) => string {
  const journey = useActiveJourney();
  const titles = useMemo(() => new Map((journey.data?.nodes ?? []).map((n) => [n.key, n.title])), [journey.data]);
  return useCallback((key: string) => titles.get(key) ?? humanizeNodeKey(key), [titles]);
}

/** Phones and tablets, where "Scan with camera" is offered. */
export function useIsTouch(): boolean {
  return useMediaQuery("(pointer: coarse)");
}

/**
 * Width of an element, kept current with a ResizeObserver. Pages sit beside a docked
 * assistant on desktop, so layout decisions follow the page's width, not the viewport's.
 */
export function useElementWidth<T extends HTMLElement>() {
  const [element, setElement] = useState<T | null>(null);
  const [width, setWidth] = useState(0);
  useLayoutEffect(() => {
    if (!element) return;
    setWidth(element.getBoundingClientRect().width);
    const observer = new ResizeObserver(([entry]) => {
      if (entry) setWidth(entry.contentRect.width);
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, [element]);
  return [setElement, width] as const;
}

/** Matches Tailwind's `@4xl/main` (56rem): wide enough for a list beside a detail panel. */
export const SPLIT_MIN_WIDTH = 896;
