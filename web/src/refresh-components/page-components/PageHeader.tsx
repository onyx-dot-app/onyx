// This should be used for *all* pages (including admin pages)

import { SvgProps } from "@/icons";
import { cn } from "@/lib/utils";
import Text from "@/refresh-components/texts/Text";

export interface PageHeaderProps {
  // Header variants
  sticky?: boolean;

  icon: React.FunctionComponent<SvgProps>;
  title: string;
  description: string;
  className?: string;
  children?: React.ReactNode;
  rightChildren?: React.ReactNode;
}

export default function PageHeader({
  icon: Icon,
  title,
  description,
  className,
  children,
  rightChildren,
  sticky = false,
}: PageHeaderProps) {
  return (
    <div className={cn("pt-10", sticky && "sticky top-0 z-10", className)}>
      <div className="flex flex-col gap-6 px-4 pt-4 pb-2">
        <div className="flex flex-col">
          <div className="flex flex-row justify-between items-center gap-4">
            <Icon className="stroke-text-04 h-[1.75rem] w-[1.75rem]" />
            {rightChildren}
          </div>
          <div className="flex flex-col">
            <Text headingH2>{title}</Text>
            <Text secondaryBody text03>
              {description}
            </Text>
          </div>
        </div>
        <div>{children}</div>
      </div>
    </div>
  );
}
