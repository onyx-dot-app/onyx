// Email/password sign-in mutation. Thin wrapper over SessionManager so screens
// get the standard TanStack mutation state (isPending / error). On success
// SessionManager has already stored the Bearer token and reset the cache, so
// the caller just needs to navigate (the auth gate reacts to /api/me).
import { useMutation } from "@tanstack/react-query";

import { login } from "@/api/auth/sessionManager";

export function useEmailLogin() {
  return useMutation({
    mutationFn: (vars: { email: string; password: string }) =>
      login({ kind: "password", email: vars.email, password: vars.password }),
  });
}
