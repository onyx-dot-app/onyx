"use client";

import { ProjectsProvider } from "@/providers/ProjectsContext";

export default function TutorLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return <ProjectsProvider>{children}</ProjectsProvider>;
}
