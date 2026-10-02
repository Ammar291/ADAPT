import { useEffect, useRef } from "react";
import { useSession } from "@/lib/api/hooks";
import { resolveLocale, setUiLocale } from ".";

/** Mounted inside the existing session gate; it never fetches or persists private records. */
export function LocaleSync() {
  const { data: user } = useSession();
  const hydratedUser = useRef<string | null>(null);
  useEffect(() => {
    if (user && hydratedUser.current !== user.id) {
      hydratedUser.current = user.id;
      void setUiLocale(resolveLocale(user.preferences.uiLocale));
    }
  }, [user?.id, user?.preferences.uiLocale]);
  return null;
}
