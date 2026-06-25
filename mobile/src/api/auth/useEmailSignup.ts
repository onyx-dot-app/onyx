// register() creates the account then logs in; on success the token's already stored, so the caller just navigates.
import { useMutation } from "@tanstack/react-query";

import { register } from "@/api/auth/sessionManager";

export function useEmailSignup() {
  return useMutation({
    mutationFn: (vars: { email: string; password: string }) => register(vars),
  });
}
