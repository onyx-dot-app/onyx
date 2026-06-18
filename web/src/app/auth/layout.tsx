import { AuthLayouts } from "@opal/layouts";

export interface LayoutProps {
  children: React.ReactNode;
}

export default function Layout({ children }: LayoutProps) {
  return <AuthLayouts.Root>{children}</AuthLayouts.Root>;
}
