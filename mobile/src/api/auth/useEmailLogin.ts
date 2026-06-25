import { useMutation } from "@tanstack/react-query";

import { login } from "@/api/auth/sessionManager";

export function useEmailLogin() {
  return useMutation({
    mutationFn: (vars: { email: string; password: string }) =>
      login({ kind: "password", email: vars.email, password: vars.password }),
  });
}
