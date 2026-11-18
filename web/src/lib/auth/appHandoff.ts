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
