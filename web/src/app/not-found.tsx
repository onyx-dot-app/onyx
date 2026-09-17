"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

// Unknown routes are sent to the login page (which bounces authenticated users
// back into the app).
//
// NOTE: this intentionally redirects on the client instead of calling
// `redirect()` during render. Next.js eagerly includes `NotFound` in every
// page's RSC payload as the not-found boundary fallback, so a server-side
// `redirect()` here throws inside every RSC render. React's dev-only Server
// Components performance track then reports the component as errored with no
// children and crashes with:
//   Failed to execute 'measure' on 'Performance': 'NotFound' cannot have a
//   negative time stamp.
// See https://github.com/vercel/next.js/issues/86060.
export default function NotFound() {
  const router = useRouter();

  useEffect(() => {
    router.replace("/auth/login");
  }, [router]);

  return null;
}
