// Single-flight session-token refresh mutation. Drives proactive refresh on
// foreground resume and reactive refresh on a 401 (both wired in a later PR);
// the single-flight guard lives in SessionManager.refreshToken so concurrent
// triggers collapse to one network call.
import { useMutation } from "@tanstack/react-query";

import { refreshToken } from "@/api/auth/sessionManager";

export function useSessionRefresh() {
  return useMutation({ mutationFn: () => refreshToken() });
}
