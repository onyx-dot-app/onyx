import type { IconProps } from "@opal/types";
import Separator from "@/refresh-components/Separator";
import Text from "@/refresh-components/texts/Text";

export interface AdminPageLayoutProps {
  children: React.ReactNode;
  icon: React.FunctionComponent<IconProps>;
  title: string;
  description: string;
  rightChildren?: React.ReactNode;
}

export interface AdminPageHeaderProps {
  icon: React.FunctionComponent<IconProps>;
  title: string;
  description: string;
  rightChildren?: React.ReactNode;
}

export function AdminPageHeader({
  icon: Icon,
  title,
  description,
  rightChildren,
}: AdminPageHeaderProps) {
  return (
    <div className="flex flex-col">
      <div className="flex flex-row justify-between items-center gap-4">
        <Icon className="stroke-text-04 h-[1.75rem] w-[1.75rem]" />
        {rightChildren}
      </div>
      <div className="flex flex-col">
        <Text headingH2 aria-label="admin-page-title">
          {title}
        </Text>
        <Text secondaryBody text03>
          {description}
        </Text>
      </div>
    </div>
  );
}

export function AdminPageLayout({
  children,
  icon,
  title,
  description,
  rightChildren,
}: AdminPageLayoutProps) {
  return (
    <div className="flex flex-col w-full h-full overflow-hidden">
      <div className="container max-w-[60rem] flex flex-col h-full overflow-hidden">
        <div className="px-4 pt-14 pb-6 gap-6 flex flex-col flex-shrink-0">
          <AdminPageHeader
            icon={icon}
            title={title}
            description={description}
            rightChildren={rightChildren}
          />
          <Separator className="py-0" />
        </div>
        <div className="px-4 pb-6 flex-1 overflow-y-auto min-h-0">
          {children}
        </div>
      </div>
    </div>
  );
}
