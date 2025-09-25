interface CardSectionProps {
  children: React.ReactNode;
  className?: string;
}

// Used for all admin page sections
export default function CardSection({ children, className }: CardSectionProps) {
  return (
    <div
      className={`p-padding-content border bg-background-tint-02 rounded-08 ${className}`}
    >
      {children}
    </div>
  );
}
