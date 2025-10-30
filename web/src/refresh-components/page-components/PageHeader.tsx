// This should be used for *all* pages (including admin pages)

import { SvgProps } from "@/icons";
import { cn } from "@/lib/utils";
import Text from "@/refresh-components/texts/Text";

export interface PageHeaderProps {
  icon: React.FunctionComponent<SvgProps>;
  title: string;
  description: string;
  children?: React.ReactNode;
  rightChildren?: React.ReactNode;
  sticky?: boolean;
}

export default function PageHeader({
  icon: Icon,
  title,
  description,
  children,
  rightChildren,
  sticky = false,
}: PageHeaderProps) {
  return (
    <div
      className={cn(
        "flex flex-col gap-6 p-4"
        // sticky && "sticky top-0 z-10"
      )}
    >
      <div className="flex flex-col">
        <div className="flex flex-row justify-between items-center gap-4">
          <Icon className="stroke-text-04 h-[1.75rem] w-[1.75rem]" />
          {rightChildren}
        </div>
        <div className="flex flex-col">
          <Text headingH2>{title}</Text>
          <Text secondaryBody>{description}</Text>
        </div>
      </div>
      {children}
    </div>
  );
}
