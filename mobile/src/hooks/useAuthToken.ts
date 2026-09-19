import { useEffect, useState } from "react";

import { getToken } from "@/api/auth/tokenStore";
import { useSession } from "@/state/session";

// Bearer token in state (async keychain read) for attaching to image request headers.
// Re-reads on server switch and on auth-state change (login/logout) so a stale bearer isn't
// kept after the session boundary moves.
export function useAuthToken(): string | null {
  const serverUrl = useSession((state) => state.serverUrl);
  const status = useSession((state) => state.status);
  const [token, setToken] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    getToken()
      .then((value) => {
        if (active) setToken(value);
      })
      .catch(() => {
        if (active) setToken(null);
      });
    return () => {
      active = false;
    };
  }, [serverUrl, status]);

  return token;
}
