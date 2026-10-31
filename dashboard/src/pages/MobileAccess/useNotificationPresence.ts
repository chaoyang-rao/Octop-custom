import { useEffect } from "react";
import { request, getAuthToken } from "../../api/request";
import { useCurrentUser } from "../../hooks/useCurrentUser";

/** Report only recent interaction and focus; never key values or message text. */
export function useNotificationPresence() {
  const userId = useCurrentUser()?.id;
  useEffect(() => {
    if (!userId) return;
    const key = "octop:notification-presence-client";
    const clientId = sessionStorage.getItem(key) || crypto.randomUUID();
    sessionStorage.setItem(key, clientId);
    let lastInteraction = 0;
    let lastReport = 0;
    let previous = false;
    const report = (force = false) => {
      if (!getAuthToken()) return;
      const active =
        document.visibilityState === "visible" &&
        document.hasFocus() &&
        Date.now() - lastInteraction < 30_000;
      if (
        !force &&
        active === previous &&
        (!active || Date.now() - lastReport < 15_000)
      )
        return;
      previous = active;
      lastReport = Date.now();
      void request<void>("/mobile-access/presence", {
        method: "POST",
        body: JSON.stringify({ client_id: clientId, active }),
      }).catch(() => undefined);
    };
    const interact = () => {
      lastInteraction = Date.now();
      report();
    };
    const focus = () => report(true);
    window.addEventListener("keydown", interact, { passive: true });
    window.addEventListener("pointerdown", interact, { passive: true });
    window.addEventListener("focus", focus);
    window.addEventListener("blur", focus);
    document.addEventListener("visibilitychange", focus);
    const timer = window.setInterval(() => report(), 10_000);
    return () => {
      clearInterval(timer);
      window.removeEventListener("keydown", interact);
      window.removeEventListener("pointerdown", interact);
      window.removeEventListener("focus", focus);
      window.removeEventListener("blur", focus);
      document.removeEventListener("visibilitychange", focus);
      if (getAuthToken())
        void request<void>("/mobile-access/presence", {
          method: "POST",
          body: JSON.stringify({ client_id: clientId, active: false }),
        }).catch(() => undefined);
    };
  }, [userId]);
}
