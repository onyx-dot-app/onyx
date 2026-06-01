// Single source of truth for auth state. SecureStore is the durable store; this context
// mirrors it in React state so screens re-render on sign-in/out. The router gates on
// `status`: "loading" (splash), "signedIn" ((app) routes), "signedOut" (redirect to login).
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
  token: string | null;
  status: AuthStatus;
  error: string | null;
  signInWithPassword: (email: string, password: string) => Promise<void>;
  signInWithGoogle: () => Promise<void>;
  // Does NOT sign in (backend may require email verification first).
  register: (email: string, password: string) => Promise<{ needsVerification: boolean }>;
  signOut: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setTokenState] = useState<string | null>(null);
  const [status, setStatus] = useState<AuthStatus>("loading");
  const [error, setError] = useState<string | null>(null);

  // Cold-start hydration: adopt a token if the app was launched by an onyx://callback
  // deep link (cold-start OAuth), else fall back to the persisted JWT in SecureStore.
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
    // network logout hangs.
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
