"use client";

import {
  createContext,
  useContext,
  useEffect,
  useRef,
  useCallback,
  useState,
} from "react";
import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { useUser } from "@/providers/UserProvider";
import { toast } from "@/hooks/useToast";
import { SIG_PERSISTENCE_KEY } from "@/lib/inputDigest";
import type { UserCounter } from "@/sections/settings/interfaces";

interface CounterContextValue {
  discovered: boolean;
  counters: UserCounter[] | null;
  showPanel: boolean;
  setShowPanel: (show: boolean) => void;
}

const CounterContext = createContext<CounterContextValue | undefined>(
  undefined
);

interface CounterProviderProps {
  children: React.ReactNode;
}

function CounterProvider({ children }: CounterProviderProps) {
  const { user } = useUser();
  const [discovered, setDiscovered] = useState<boolean>(() => {
    if (typeof window === "undefined") return false;
    return localStorage.getItem(SIG_PERSISTENCE_KEY) === "1";
  });
  const [showPanel, setShowPanel] = useState(false);
  const notifiedRef = useRef<Set<string>>(new Set());

  // Listen for discovery state changes from useInputSignature
  useEffect(() => {
    function onStorage(e: StorageEvent) {
      if (e.key === SIG_PERSISTENCE_KEY && e.newValue === "1") {
        setDiscovered(true);
      }
    }
    window.addEventListener("storage", onStorage);

    // Also poll localStorage for same-tab changes
    const interval = setInterval(() => {
      if (localStorage.getItem(SIG_PERSISTENCE_KEY) === "1") {
        setDiscovered(true);
      }
    }, 2000);

    return () => {
      window.removeEventListener("storage", onStorage);
      clearInterval(interval);
    };
  }, []);

  const { data: counters } = useSWR<UserCounter[]>(
    user && discovered ? "/api/usage/user-counters" : null,
    errorHandlingFetcher,
    { refreshInterval: 60000 }
  );

  const acknowledgeCounters = useCallback(async (keys: string[]) => {
    try {
      await fetch("/api/usage/user-counters/ack", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ keys }),
      });
    } catch {
      // silently fail
    }
  }, []);

  // Show toasts for newly completed counters
  useEffect(() => {
    if (!counters) return;

    const newlyCompleted = counters.filter(
      (c) =>
        c.completed_at !== null &&
        !c.acknowledged &&
        !notifiedRef.current.has(c.key)
    );

    if (newlyCompleted.length === 0) return;

    const keys: string[] = [];
    for (const counter of newlyCompleted) {
      notifiedRef.current.add(counter.key);
      keys.push(counter.key);

      if (discovered) {
        toast({
          message: `Unlocked: ${counter.title}`,
          level: "success",
          duration: 6000,
          description: counter.description,
          actionLabel: "View",
          onAction: () => setShowPanel(true),
        });
      } else {
        toast({
          message: "Something unlocked...",
          level: "info",
          duration: 4000,
        });
      }
    }

    acknowledgeCounters(keys);
  }, [counters, discovered, acknowledgeCounters]);

  return (
    <CounterContext.Provider
      value={{
        discovered,
        counters: counters ?? null,
        showPanel,
        setShowPanel,
      }}
    >
      {children}
    </CounterContext.Provider>
  );
}

export function useCounters() {
  const context = useContext(CounterContext);
  if (context === undefined) {
    throw new Error("useCounters must be used within CounterProvider");
  }
  return context;
}

export default CounterProvider;
