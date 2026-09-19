"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { usePathname } from "next/navigation";
import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";

interface IncognitoAvailabilityResponse {
  available: boolean;
}

// Shared incognito state so the toggle, submit path, and warning stay in
// sync. Locks once the chat has a message, since the mode pins at creation.
// Availability only gates the toggle. The server enforces it on creation.
interface IncognitoContextValue {
  incognitoAvailable: boolean;
  incognitoEnabled: boolean;
  // Always-current mirror of incognitoEnabled. Send paths must read this at
  // submit time: a stale closure over the boolean submits a persisted chat
  // while the UI shows incognito.
  incognitoEnabledRef: React.RefObject<boolean>;
  incognitoLocked: boolean;
  // Minted when incognito is switched on and sent with every upload, so a file
  // names its session before the first message creates it.
  incognitoSessionId: string | null;
  toggleIncognito: () => void;
  setIncognitoSessionId: (sessionId: string | null) => void;
  setIncognitoEnabled: (enabled: boolean) => void;
  setIncognitoLocked: (locked: boolean) => void;
}

const IncognitoContext = createContext<IncognitoContextValue | null>(null);

interface IncognitoProviderProps {
  children: React.ReactNode;
}

export function IncognitoProvider({ children }: IncognitoProviderProps) {
  const [incognitoEnabled, setIncognitoEnabled] = useState(false);
  const [incognitoLocked, setIncognitoLocked] = useState(false);

  const { data: availability, mutate: revalidateAvailability } =
    useSWR<IncognitoAvailabilityResponse>(
      SWR_KEYS.incognitoAvailability,
      errorHandlingFetcher,
      {
        // Hiding the toggle is the safe fallback, but a persistent failure
        // otherwise looks identical to the admin turning incognito off.
        onError: (error) =>
          console.error("Failed to load incognito availability:", error),
      }
    );
  const incognitoAvailable = availability?.available ?? false;

  // The provider mounts once for the whole app, so route changes never
  // remount the hook. Revalidating per navigation picks up admin changes to
  // the availability setting or group flags without a hard refresh.
  const pathname = usePathname();
  useEffect(() => {
    void revalidateAvailability();
  }, [pathname, revalidateAvailability]);

  const [incognitoSessionId, setIncognitoSessionId] = useState<string | null>(
    null
  );
  const toggleIncognito = useCallback(() => {
    if (incognitoLocked) return;
    const next = !incognitoEnabled;
    setIncognitoSessionId(next ? crypto.randomUUID() : null);
    setIncognitoEnabled(next);
  }, [incognitoLocked, incognitoEnabled]);

  const incognitoEnabledRef = useRef(false);
  useEffect(() => {
    incognitoEnabledRef.current = incognitoEnabled;
  }, [incognitoEnabled]);

  // Memoized so consumers keying callbacks on the context object do not
  // rebuild them on every provider render.
  const value = useMemo(
    () => ({
      incognitoAvailable,
      incognitoEnabled,
      incognitoEnabledRef,
      incognitoLocked,
      incognitoSessionId,
      toggleIncognito,
      setIncognitoEnabled,
      setIncognitoSessionId,
      setIncognitoLocked,
    }),
    [
      incognitoAvailable,
      incognitoEnabled,
      incognitoLocked,
      incognitoSessionId,
      toggleIncognito,
    ]
  );

  return (
    <IncognitoContext.Provider value={value}>
      {children}
    </IncognitoContext.Provider>
  );
}

export function useIncognito(): IncognitoContextValue {
  const ctx = useContext(IncognitoContext);
  if (!ctx) {
    throw new Error("useIncognito must be used within an IncognitoProvider");
  }
  return ctx;
}

// For components that also render outside the provider (e.g. shared chats),
// where incognito can never be active.
export function useIncognitoOptional(): IncognitoContextValue | null {
  return useContext(IncognitoContext);
}
