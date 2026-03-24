"use client";

import { SWRConfig } from "swr";
import { skipRetryOnAuthError } from "@/lib/fetcher";

export default function SWRConfigProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <SWRConfig value={{ onErrorRetry: skipRetryOnAuthError }}>
      {children}
    </SWRConfig>
  );
}
