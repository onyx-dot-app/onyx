import { cn } from "@/lib/utils";
import { WithoutStyles } from "@/types";
import CopyIconButton from "@/refresh-components/buttons/CopyIconButton";

interface CodeProps extends WithoutStyles<React.HTMLAttributes<HTMLElement>> {
  children: string;
  showCopyButton?: boolean;
  /** When true the copy button is always visible instead of only on hover. */
  alwaysShowCopy?: boolean;
}

export default function Code({
  children,
  showCopyButton = true,
  alwaysShowCopy = false,
  ...props
}: CodeProps) {
  return (
    <div className="relative code-wrapper">
      <code className={cn("code-block", alwaysShowCopy && "pr-8")} {...props}>
        {children}
      </code>
      {showCopyButton && (
        <div
          className={cn("code-copy-button", alwaysShowCopy && "opacity-100")}
        >
          <CopyIconButton getCopyText={() => children} />
        </div>
      )}
    </div>
  );
}
