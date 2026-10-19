/**
 * The extension shares the JobBot website's session
 * instead of signing in separately. On the JobBot site (top frame only) this
 * reads the site's session token and hands it to the background — on load, when
 * another tab changes it, and on a short poll for same-tab sign-in/sign-out.
 */
import { WEB_ORIGIN } from "../lib/env";
import { bg } from "../lib/messaging";

const WEB_TOKEN_KEY = "jobbot_access_token"; // frontend/src/auth/api.ts TOKEN_KEY

export function initSessionSync(): void {
  if (window.top !== window.self || location.origin !== WEB_ORIGIN) return;
  let last: string | null | undefined;
  const sync = () => {
    let token: string | null = null;
    try {
      token = localStorage.getItem(WEB_TOKEN_KEY);
    } catch {
      return;
    }
    if (token === last) return;
    last = token;
    void bg.syncSession(token);
  };
  sync();
  window.addEventListener("storage", (e) => {
    if (e.key === WEB_TOKEN_KEY || e.key === null) sync();
  });
  window.setInterval(sync, 3000);
}
