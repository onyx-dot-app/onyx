import { useMutation } from "@tanstack/react-query";

import { login } from "@/api/auth/sessionManager";
import type { ProviderDescriptor } from "@/api/auth/providers";

export function useBrowserLogin() {
  return useMutation({
    mutationFn: (provider: ProviderDescriptor) =>
      login({ kind: "browser", provider }),
  });
}
