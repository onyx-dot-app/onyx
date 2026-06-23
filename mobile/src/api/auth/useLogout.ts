// Logout mutation. SessionManager.logout best-effort-revokes server-side, then
// wipes the local token + query cache regardless of network outcome.
import { useMutation } from "@tanstack/react-query";

import { logout } from "@/api/auth/sessionManager";

export function useLogout() {
  return useMutation({ mutationFn: () => logout() });
}
