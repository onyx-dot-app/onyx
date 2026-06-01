// Single source of truth for auth state. SecureStore is the durable store; this context
// mirrors it in React state so screens re-render on sign-in/out. The router gates on
// `status`: "loading" (splash), "noDomain" (no server URL yet -> domain screen),
// "signedIn" ((app) routes), "signedOut" (redirect to login).
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";

import * as Linking from "expo-linking";

import { clearServerUrl, hydrateServerUrl } from "@/lib/serverUrl";
import {
  loginWithPassword,
  loginWithGoogle,
  register as registerAccount,
  logout,
  extractTokenFromUrl,
} from "./authClient";
import { getToken, setToken, deleteToken } from "./secureStore";

export type AuthStatus = "loading" | "noDomain" | "signedIn" | "signedOut";

export interface AuthContextValue {
  token: string | null;
  status: AuthStatus;
  error: string | null;
  signInWithPassword: (email: string, password: string) => Promise<void>;
  signInWithGoogle: () => Promise<void>;
  // Does NOT sign in (backend may require email verification first).
  register: (email: string, password: string) => Promise<{ needsVerification: boolean }>;
  signOut: () => Promise<void>;
  // Re-run startup hydration (server URL + token). Called after the domain screen
  // saves a URL so the gate moves off "noDomain".
  refresh: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setTokenState] = useState<string | null>(null);
  const [status, setStatus] = useState<AuthStatus>("loading");
  const [error, setError] = useState<string | null>(null);

  // Startup hydration: first resolve the server URL — without one there's nothing to
  // talk to, so gate to the domain screen. With one, adopt a token from an
  // onyx://callback deep link (cold-start OAuth) or the persisted JWT in SecureStore.
  // Exposed as `refresh` so the domain screen can re-run it after saving a URL.
  const runHydration = useCallback(async () => {
    try {
      const server = await hydrateServerUrl();
      if (!server) {
        setStatus("noDomain");
        return;
      }
      const initialUrl = await Linking.getInitialURL();
      const tokenFromUrl = initialUrl ? extractTokenFromUrl(initialUrl) : null;
      const resolved = tokenFromUrl ?? (await getToken());
      if (tokenFromUrl) await setToken(tokenFromUrl);
      setTokenState(resolved);
      setStatus(resolved ? "signedIn" : "signedOut");
    } catch {
      // SecureStore read failed (rare) — treat as signed out so the user can retry.
      setTokenState(null);
      setStatus("signedOut");
    }
  }, []);

  useEffect(() => {
    // Inline async wrapper so the setState calls land after awaits (not synchronously
    // in the effect body) — the standard mount-hydration pattern.
    void (async () => {
      await runHydration();
    })();
  }, [runHydration]);

  // Shared tail of every sign-in path: persist + flip to signedIn + clear error.
  const adoptToken = useCallback(async (jwt: string) => {
    await setToken(jwt);
    setTokenState(jwt);
    setStatus("signedIn");
    setError(null);
  }, []);

  // Clear prior error, run the action, and on failure surface a readable message
  // before rethrowing so the screen can react too.
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
    // Clear local state first so the UI never shows a stale signed-in screen if the
    // network logout hangs. Logout returns to the START of the funnel (domain entry),
    // so go to "noDomain" — not "signedOut".
    setTokenState(null);
    setStatus("noDomain");
    setError(null);
    // Wipe all per-user client state (chat sessions, query cache, MMKV) so a different
    // user signing in on this device can't see the previous user's data. Dynamic import
    // avoids an auth <-> query/client module cycle; best-effort (never block sign-out).
    try {
      const { clearUserData } = await import("@/state/clearUserData");
      clearUserData();
    } catch {
      // ignore — local token is already cleared, which is the security-critical part
    }
    if (current) {
      await logout(current); // best-effort; uses the still-set server URL
    }
    await deleteToken();
    // Forget the server URL LAST (after logout used it) so logout returns to the
    // domain-entry screen.
    await clearServerUrl();
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
        refresh: runHydration,
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
