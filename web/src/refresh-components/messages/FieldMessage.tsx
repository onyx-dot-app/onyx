import { cn } from "@/lib/utils";
import React from "react";
import Text from "../texts/Text";
import {
  SvgAlertCircle,
  SvgCheckCircle,
  SvgLoader,
  SvgXOctagon,
} from "@opal/icons";
type MessageVariant =
  | "error"
  | "success"
  | "loading"
  | "warning"
  | "info"
  | "idle";

const iconMap: Record<MessageVariant, React.ReactNode> = {
  error: <SvgXOctagon className="h-3 w-3 stroke-status-error-05" />,
  success: <SvgCheckCircle className="h-3 w-3 stroke-status-success-05" />,
  loading: <SvgLoader className="h-3 w-3 stroke-text-02 animate-spin" />,
  warning: <SvgAlertCircle className="h-3 w-3 stroke-status-warning-05" />,
  info: <SvgAlertCircle className="h-3 w-3 stroke-text-03" />,
  idle: null,
};

interface FieldMessageRootProps extends React.HTMLAttributes<HTMLDivElement> {
  variant: MessageVariant;
  children: React.ReactNode;
}

const FieldMessageRoot: React.FC<FieldMessageRootProps> = ({
  variant,
  className,
  children,
  ...props
}) => {
  const icon = iconMap[variant];

  return (
    <div
      className={cn("flex flex-row items-center gap-x-0.5", className)}
      {...props}
    >
      {icon !== null && (
        <div className="w-4 h-4 flex items-center justify-center">{icon}</div>
      )}
      {children}
    </div>
  );
};

interface FieldMessageContentProps
  extends React.HTMLAttributes<HTMLParagraphElement> {
  children: React.ReactNode;
}

const FieldMessageContent: React.FC<FieldMessageContentProps> = ({
  className,
  children,
  ...props
}) => {
  return (
    <Text
      as="p"
      text03
      secondaryBody
      className={cn("ml-0.5", className)}
      {...props}
    >
      {children}
    </Text>
  );
};

export const FieldMessage = Object.assign(FieldMessageRoot, {
  Content: FieldMessageContent,
});
