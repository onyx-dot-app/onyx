"use client";

import { ReactNode } from "react";
import { AvatarProvider } from "./AvatarContext";

export default function AvatarProviderWrapper({
  children,
}: {
  children: ReactNode;
}) {
  return <AvatarProvider>{children}</AvatarProvider>;
}
