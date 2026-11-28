import { cn } from "@opal/utils";

interface UnseenMarkerProps {
  label: string;
  className?: string;
}

export default function UnseenMarker({ label, className }: UnseenMarkerProps) {
  return (
    <span
      role="img"
      aria-label={label}
      className={cn("size-2 rounded-full bg-status-info-05", className)}
    />
  );
}
