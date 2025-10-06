import { cn } from "@/lib/utils";

export interface CardSectionProps {
  className?: string;
  children?: React.ReactNode;
}

// Used for all admin page sections
export default function CardSection({ children, className }: CardSectionProps) {
  return (
    <div
      className={cn(
        "p-padding-content bg-background-neutral-00 rounded-16 border",
        className
      )}
    >
      {children}
    </div>
  );
}
