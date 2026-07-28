import { useMutation } from "@tanstack/react-query";

import { logout } from "@/api/auth/sessionManager";

export function useLogout() {
  return useMutation({ mutationFn: () => logout() });
}
