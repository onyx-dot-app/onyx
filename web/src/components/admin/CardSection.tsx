import { cn } from "@/lib/utils";

// Used for all admin page sections
export default function CardSection({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "p-6 border bg-[#fff] dark:bg-neutral-800 rounded border-neutral-200 dark:border-neutral-700",
        className
      )}
    >
      {children}
    </div>
  );
}
