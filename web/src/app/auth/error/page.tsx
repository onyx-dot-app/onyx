"use client";

import AuthErrorContent from "./AuthErrorContent";
import { useSearchParams } from "next/navigation";

function Page() {
  const searchParams = useSearchParams();
  const error = searchParams?.get("error") || null;

  return <AuthErrorContent message={error} />;
}

export default Page;
