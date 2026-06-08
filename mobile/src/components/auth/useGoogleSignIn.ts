import { useAuth, SignInCancelledError } from "@/auth";

// Shared "Continue with Google" handler for login and register. Callers pass
// their own setError/setBusy so the hook drives the screen's shared form state.
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
      // A user-initiated cancel isn't worth surfacing.
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
