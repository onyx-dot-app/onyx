// AuthProvider — the single source of truth for the app's auth state.
//
// Holds the in-memory JWT + a coarse status the router gates on:
//   "loading"   -> still resolving the token on cold start; render a splash.
//   "signedIn"  -> a JWT is present; the (app) routes are reachable.
//   "signedOut" -> no token; the router redirects to (auth)/login.
//
// SecureStore is the durable store; this context mirrors it in React state so
// screens re-render on sign-in/out. The integrator wraps the app in <AuthProvider>
// (in app/_layout.tsx) and reads useAuth() from the router + auth screens.
//
// Three entry points all converge on "store the JWT, flip to signedIn":
//   signInWithPassword -> email/password login
//   signInWithGoogle   -> system-browser Google OAuth
//   register           -> create an account (does NOT sign in; backend may require
//                         email verification first, so the user logs in afterward)
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";

import * as Linking from "expo-linking";

import {
  loginWithPassword,
  loginWithGoogle,
  register as registerAccount,
  logout,
  extractTokenFromUrl,
} from "./authClient";
import { getToken, setToken, deleteToken } from "./secureStore";

export type AuthStatus = "loading" | "signedIn" | "signedOut";

export interface AuthContextValue {
  /** The raw JWT, or null when signed out / still loading. Opaque — send verbatim. */
  token: string | null;
  /** Coarse status the router gates on. */
  status: AuthStatus;
  /** Last surfaced auth error message (e.g. bad credentials), or null. */
  error: string | null;
  /** Email/password login: store the JWT, flip to "signedIn". Throws on failure. */
  signInWithPassword: (email: string, password: string) => Promise<void>;
  /** System-browser Google OAuth: store the JWT, flip to "signedIn". Throws on cancel. */
  signInWithGoogle: () => Promise<void>;
  /** Create an account. Does NOT sign in (backend may require verification first). */
  register: (email: string, password: string) => Promise<{ needsVerification: boolean }>;
  /** Best-effort server logout, clear stored JWT, flip to "signedOut". Never throws. */
  signOut: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setTokenState] = useState<string | null>(null);
  const [status, setStatus] = useState<AuthStatus>("loading");
  const [error, setError] = useState<string | null>(null);

  // Cold-start hydration. First check whether the app was *launched* by an
  // onyx://callback#token=... deep link (the cold-start OAuth path) and adopt that
  // token; otherwise fall back to the persisted JWT in SecureStore.
  useEffect(() => {
    let active = true;
    (async () => {
      try {
        const initialUrl = await Linking.getInitialURL();
        const tokenFromUrl = initialUrl ? extractTokenFromUrl(initialUrl) : null;
        const resolved = tokenFromUrl ?? (await getToken());
        if (!active) return;
        if (tokenFromUrl) await setToken(tokenFromUrl);
        setTokenState(resolved);
        setStatus(resolved ? "signedIn" : "signedOut");
      } catch {
        // SecureStore read failed (rare) — treat as signed out so the user can retry.
        if (!active) return;
        setTokenState(null);
        setStatus("signedOut");
      }
    })();
    return () => {
      active = false;
    };
  }, []);

  // Shared tail of every sign-in path: persist + flip to signedIn + clear error.
  const adoptToken = useCallback(async (jwt: string) => {
    await setToken(jwt);
    setTokenState(jwt);
    setStatus("signedIn");
    setError(null);
  }, []);

  // Shared head of every auth action: clear the prior error, run the action, and on
  // failure surface a readable message before rethrowing so the screen can react too.
  const runAuthAction = useCallback(
    async <T,>(fn: () => Promise<T>, fallbackMsg: string): Promise<T> => {
      setError(null);
      try {
        return await fn();
      } catch (e) {
        setError(e instanceof Error ? e.message : fallbackMsg);
        throw e; // let the screen also react (e.g. stop its spinner)
      }
    },
    [],
  );

  const signInWithPassword = useCallback(
    (email: string, password: string) =>
      runAuthAction(async () => {
        await adoptToken(await loginWithPassword(email, password));
      }, "Sign-in failed."),
    [adoptToken, runAuthAction],
  );

  const signInWithGoogle = useCallback(
    () =>
      runAuthAction(async () => {
        await adoptToken(await loginWithGoogle());
      }, "Sign-in failed."),
    [adoptToken, runAuthAction],
  );

  const register = useCallback(
    (email: string, password: string) =>
      runAuthAction(() => registerAccount(email, password), "Could not create your account."),
    [runAuthAction],
  );

  const signOut = useCallback(async () => {
    const current = token;
    // Optimistically clear local state first so the UI never shows a stale
    // signed-in screen even if the network logout hangs.
    setTokenState(null);
    setStatus("signedOut");
    setError(null);
    if (current) {
      await logout(current); // best-effort; swallows its own errors
    }
    await deleteToken();
  }, [token]);

  return (
    <AuthContext.Provider
      value={{
        token,
        status,
        error,
        signInWithPassword,
        signInWithGoogle,
        register,
        signOut,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

/** Access the auth context. Throws if used outside <AuthProvider>. */
export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used within an <AuthProvider>.");
  }
  return ctx;
}
