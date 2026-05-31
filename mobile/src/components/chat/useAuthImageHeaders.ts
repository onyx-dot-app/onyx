import { useEffect, useState } from "react";

import { getAuthHeaders } from "@/auth";

// Resolves the bearer auth headers once, for `expo-image` remote sources that
// hit authed backend routes (`GET /chat/file/{id}`). Returns `undefined` until
// loaded; expo-image simply begins loading once headers arrive. Web rides cookies
// for the same `<img src>`, so it needs no equivalent.
export function useAuthImageHeaders(): Record<string, string> | undefined {
  const [headers, setHeaders] = useState<Record<string, string> | undefined>(
    undefined,
  );

  useEffect(() => {
    let active = true;
    void (async () => {
      const resolved = await getAuthHeaders();
      if (!active) return;
      const record: Record<string, string> = {};
      new Headers(resolved).forEach((value, key) => {
        record[key] = value;
      });
      setHeaders(record);
    })();
    return () => {
      active = false;
    };
  }, []);

  return headers;
}
