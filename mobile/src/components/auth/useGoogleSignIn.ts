import { useAuth, SignInCancelledError } from "@/auth";

// Shared "Continue with Google" handler for the login and register screens.
// Identical in both places except for which error-setter the catch writes to,
// so callers pass their own setError. The screens own a single `busy` flag that
// also gates their password/register form, so the caller passes setBusy too and
// the hook toggles that shared state rather than holding its own. A
// user-initiated cancel is not an error worth surfacing loudly, so
// SignInCancelledError is swallowed.
export function useGoogleSignIn(
  setError: (message: string | null) => void,
  setBusy: (busy: boolean) => void,
) {
  const { signInWithGoogle } = useAuth();

  return async function handleGoogleSignIn() {
    setError(null);
    setBusy(true);
    try {
      await signInWithGoogle();
    } catch (e) {
      if (!(e instanceof SignInCancelledError)) {
        setError(
          e instanceof Error ? e.message : "Sign-in failed. Please try again.",
        );
      }
    } finally {
      setBusy(false);
    }
  };
}
