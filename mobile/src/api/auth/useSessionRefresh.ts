import { useMutation } from "@tanstack/react-query";

import { refreshToken } from "@/api/auth/sessionManager";

export function useSessionRefresh() {
  return useMutation({ mutationFn: () => refreshToken() });
}
