import { WithoutStyles } from "@/types";
import CopyIconButton from "@/refresh-components/buttons/CopyIconButton";

interface CodeProps extends WithoutStyles<React.HTMLAttributes<HTMLElement>> {
  children: string;
}

export default function Code({ children, ...props }: CodeProps) {
  return (
    <div className="relative code-wrapper">
      <code className="code-block" {...props}>
        {children}
      </code>
      <div className="code-copy-button">
        <CopyIconButton getCopyText={() => children} />
      </div>
    </div>
  );
}
