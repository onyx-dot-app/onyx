import { cn } from "@/lib/utils";

interface CalloutProps {
  icon?: React.ReactNode;
  children?: React.ReactNode;
  type?: "default" | "warning" | "danger" | "notice";
  className?: string;
}

export function Callout({
  children,
  icon,
  type = "default",
  title,
  className,
  ...props
}: CalloutProps & { title?: string }) {
  return (
    <div
      className={cn(
        "my-6 flex items-start rounded-md border border-l-4 p-4",
        className,
        {
          "border-rose-300 bg-rose-50": type === "danger",
          "border-amber-300 bg-amber-50": type === "warning",
          "border-sky-300 bg-sky-50": type === "notice",
        }
      )}
      {...props}
    >
      {icon && <span className="mr-4 text-2xl">{icon}</span>}
      <div className="flex-1">
        {title && (
          <div className="font-medium mb-1 flex items-center">{title}</div>
        )}
        {children}
      </div>
    </div>
  );
}
