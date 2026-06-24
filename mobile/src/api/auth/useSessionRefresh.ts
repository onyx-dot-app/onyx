// Single-flight guard lives in SessionManager.refreshToken, so concurrent triggers collapse to one network call.
import { useMutation } from "@tanstack/react-query";

import { refreshToken } from "@/api/auth/sessionManager";

export function useSessionRefresh() {
  return useMutation({ mutationFn: () => refreshToken() });
}
