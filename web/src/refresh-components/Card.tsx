import { cn } from "@/lib/utils";

export default function Card({
  children,
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "bg-background-tint-00 p-4 flex flex-col gap-4 border rounded-16",
        className
      )}
      {...props}
    >
      {children}
    </div>
  );
}
