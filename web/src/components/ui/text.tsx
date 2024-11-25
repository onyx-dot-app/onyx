import { cn } from "@/lib/utils";

export default function Text({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return <p className={cn("text-sm", className)}>{children}</p>;
}
