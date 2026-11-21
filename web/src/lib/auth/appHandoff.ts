// Native apps (desktop, mobile) sign in through the web OAuth flow with Onyx's
// mobile SSO parameters. The backend then finishes with a 302 to the app's
// deep link carrying a one-time code, and sets no web session cookie. The
// backend only issues allowlisted deep links (MOBILE_ALLOWED_REDIRECT_URIS).
const APP_SIGN_IN_CALLBACK = "onyx://auth/callback";

/** Whether a callback redirect hands the sign-in back to a native app. */
export function isAppSignInHandoff(
  location: string | null
): location is string {
  if (!location) return false;
  try {
    const url = new URL(location);
    return (
      `${url.protocol}//${url.host}${url.pathname}` === APP_SIGN_IN_CALLBACK
    );
  } catch {
    return false;
  }
}

/** The web page that finishes a native app's sign-in in a desktop browser. */
export const APP_SIGN_IN_HANDOFF_PATH = "/auth/app-handoff";

// Phones and tablets sign in inside an in-app auth session, which needs the
// deep link as a plain redirect. iPadOS can report a Mac user agent; its auth
// session also completes when the handoff page opens the link.
const MOBILE_USER_AGENT = /Android|iPhone|iPad|iPod|Mobile/i;
const DESKTOP_USER_AGENT = /Macintosh|Windows|X11|Linux|CrOS/i;

/**
 * Where the callback sends a finished native-app sign-in. A desktop browser
 * gets the handoff page, which opens the app and ends the tab on an Onyx page;
 * a bare redirect to the deep link leaves the tab on the identity provider's
 * last page. The deep link goes in the fragment, which is never sent to a
 * server.
 */
export function appSignInRedirect(
  deepLink: string,
  userAgent: string | null,
  appDomain: string
): string {
  const agent = userAgent ?? "";
  if (MOBILE_USER_AGENT.test(agent) || !DESKTOP_USER_AGENT.test(agent)) {
    return deepLink;
  }
  const page = new URL(APP_SIGN_IN_HANDOFF_PATH, appDomain);
  page.hash = encodeURIComponent(deepLink);
  return page.toString();
}
