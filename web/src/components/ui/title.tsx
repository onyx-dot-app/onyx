import { cn } from "@/lib/utils";

export default function Title({
  children,
  className,
  size = "sm",
}: {
  children: React.ReactNode;
  className?: string;
  size?: "lg" | "md" | "sm";
}) {
  return (
    <h1
      className={cn(
        "text-lg text-text-800 font-medium",
        size === "lg" && "text-2xl",
        size === "md" && "text-xl",
        size === "sm" && "text-lg",
        className
      )}
    >
      {children}
    </h1>
  );
}
