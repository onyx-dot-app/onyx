import { LogoType } from "@/components/logo/Logo";

interface ErrorPageLayoutProps {
  children: React.ReactNode;
}

export default function ErrorPageLayout({ children }: ErrorPageLayoutProps) {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-spacing-headline bg-background px-spacing-paragraph py-spacing-block">
      <div className="flex max-w-[220px] items-center justify-center">
        <LogoType size="large" />
      </div>
      <div className="w-full max-w-xl rounded-16 border bg-background-neutral-00 shadow-01">
        <div className="flex flex-col gap-spacing-paragraph p-padding-content">
          {children}
        </div>
      </div>
    </div>
  );
}
