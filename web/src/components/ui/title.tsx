import { cn } from "@/lib/utils";

export default function Title({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <h1 className={cn("text-lg text-text-800 font-medium", className)}>
      {children}
    </h1>
  );
}
