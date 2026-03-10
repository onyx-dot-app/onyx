import { WithoutStyles } from "@/types";
import CopyIconButton from "@/refresh-components/buttons/CopyIconButton";

interface CodeProps extends WithoutStyles<React.HTMLAttributes<HTMLElement>> {
  children: string;
  showCopyButton?: boolean;
}

export default function Code({
  children,
  showCopyButton = true,
  ...props
}: CodeProps) {
  return (
    <div className="relative code-wrapper">
      <code className="code-block" {...props}>
        {children}
      </code>
      {showCopyButton && (
        <div className="code-copy-button">
          <CopyIconButton getCopyText={() => children} />
        </div>
      )}
    </div>
  );
}
