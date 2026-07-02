import { useEffect, useState } from "react";

import { getToken } from "@/api/auth/tokenStore";
import { useSession } from "@/state/session";

// Bearer token in state (async keychain read) for attaching to image request headers.
export function useAuthToken(): string | null {
  const serverUrl = useSession((state) => state.serverUrl);
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
  }, [serverUrl]);

  return token;
}
