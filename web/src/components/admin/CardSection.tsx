import { cn } from "@/lib/utils";

export interface CardSectionProps extends React.HTMLAttributes<HTMLDivElement> {
  className?: string;
  children?: React.ReactNode;
}

// Used for all admin page sections
export default function CardSection({
  children,
  className,
  ...props
}: CardSectionProps) {
  return (
    <div
      {...props}
      className={cn(
        "p-6 bg-background-neutral-00 rounded-16 border",
        className
      )}
    >
      {children}
    </div>
  );
}
