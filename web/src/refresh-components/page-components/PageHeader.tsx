// This should be used for *all* pages (including admin pages)

import { SvgProps } from "@/icons";
import { cn } from "@/lib/utils";
import CreateButton from "@/refresh-components/buttons/CreateButton";
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
      <div className="flex flex-row justify-between items-center gap-4">
        <Icon className="stroke-text-04 h-[1.75rem] w-[1.75rem]" />
        <CreateButton primary secondary={undefined}>
          New Agent
        </CreateButton>
      </div>
      <Text headingH2>Agents &amp; Assistants</Text>
      {/*<div className="flex flex-row items-center justify-between">
        <div className="flex flex-row items-center gap-3">
          <Icon className="w-8 h-8" />
          <div className="flex flex-col">
            <h1 className="text-2xl font-semibold">{title}</h1>
            <p className="text-sm text-text-secondary">{description}</p>
          </div>
        </div>
        {rightChildren && <div>{rightChildren}</div>}
      </div>
      {children}*/}
    </div>
  );
}
