import type { Metadata } from "next";
import { generateFaviconMetadata } from "@/lib/app/svcSS";
import AuthChrome from "@/layouts/chromes/AuthChrome";

export async function generateMetadata(): Promise<Metadata> {
  return { icons: await generateFaviconMetadata() };
}

export interface LayoutProps {
  children: React.ReactNode;
}

export default function Layout({ children }: LayoutProps) {
  return <AuthChrome>{children}</AuthChrome>;
}
