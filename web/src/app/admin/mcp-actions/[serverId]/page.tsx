"use client";

import { use } from "react";
import MCPServerDetailPage from "@/sections/actions/MCPServerDetailPage";

export default function Page({
  params,
}: {
  params: Promise<{ serverId: string }>;
}) {
  const { serverId } = use(params);
  return <MCPServerDetailPage key={serverId} serverId={Number(serverId)} />;
}
