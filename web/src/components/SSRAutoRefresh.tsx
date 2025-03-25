"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

// NOTE: this is causing crashes due to `ECONNRESET` and `UND_ERR_SOCKET`
// during the server-side fetch. Should not be used until this is resolved.
// export function SSRAutoRefresh({ refreshFreq = 5 }: { refreshFreq?: number }) {
//   // Helper which automatically refreshes a SSR page X seconds
//   const router = useRouter();

//   useEffect(() => {
//     const interval = setInterval(() => {
//       router.refresh();
//     }, refreshFreq * 1000);

//     return () => clearInterval(interval);
//   }, []);

//   return <></>;
// }

export function InstantSSRAutoRefresh() {
  const router = useRouter();

  useEffect(() => {
    router.refresh();
  }, [router]);

  return <></>;
}
