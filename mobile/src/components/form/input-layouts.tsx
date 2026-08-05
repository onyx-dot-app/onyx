// Spacing uses explicit margins, not `gap` (unreliable in NativeWind on RN).
import type { ReactNode } from "react";
import { View } from "react-native";

import { Icon } from "@/components/ui/icon";
import { Separator } from "@/components/ui/separator";
import { Text } from "@/components/ui/text";
import { cn } from "@/lib/utils";
import type { IconFunctionComponent } from "@/icons/types";
import SvgAlertCircle from "@/icons/alert-circle";
import SvgXOctagon from "@/icons/x-octagon";

export type InputErrorType = "error" | "warning";

interface InputLayoutBaseProps {
  title: string;
  description?: string;
  /** "optional" renders "(Optional)"; any other string verbatim. */
  suffix?: "optional" | (string & {});
  /** Pre-resolved message; these primitives never read RHF. */
  error?: string;
  errorType?: InputErrorType;
  disabled?: boolean;
  children: ReactNode;
  className?: string;
}

export interface LabelProps {
  title: string;
  description?: string;
  suffix?: "optional" | (string & {});
  disabled?: boolean;
}

function Label({ title, description, suffix, disabled }: LabelProps) {
  return (
    <View className={cn(disabled && "opacity-50")}>
      <View className="flex-row items-center">
        <Text font="main-ui-action" color="text-04">
          {title}
        </Text>
        {suffix ? (
          <Text font="secondary-body" color="text-03" className="ml-4">
            {suffix === "optional" ? "(Optional)" : suffix}
          </Text>
        ) : null}
      </View>
      {description ? (
        <Text font="secondary-body" color="text-03" className="mt-4">
          {description}
        </Text>
      ) : null}
    </View>
  );
}

export interface InputErrorTextProps {
  children?: string;
  type?: InputErrorType;
}

function InputErrorText({ children, type = "error" }: InputErrorTextProps) {
  if (!children) return null;
  const icon = type === "error" ? SvgXOctagon : SvgAlertCircle;
  const color =
    type === "error" ? "text-status-error-05" : "text-status-warning-05";
  return (
    <View
      className="flex-row items-center"
      accessible
      accessibilityRole="alert"
      accessibilityLiveRegion="polite"
    >
      <Icon as={icon} size={12} className={cn("mr-4", color)} />
      <Text
        font="secondary-body"
        color="inherit"
        className={cn("flex-1", color)}
      >
        {children}
      </Text>
    </View>
  );
}

export interface VerticalProps extends InputLayoutBaseProps {
  subDescription?: string;
}

function Vertical({
  title,
  description,
  suffix,
  error,
  errorType = "error",
  subDescription,
  disabled,
  children,
  className,
}: VerticalProps) {
  return (
    <View className={cn("w-full", disabled && "opacity-50", className)}>
      <Label title={title} description={description} suffix={suffix} />
      <View className="mt-4">{children}</View>
      {error ? (
        <View className="mt-4">
          <InputErrorText type={errorType}>{error}</InputErrorText>
        </View>
      ) : null}
      {subDescription ? (
        <Text font="secondary-body" color="text-03" className="mt-4">
          {subDescription}
        </Text>
      ) : null}
    </View>
  );
}

export interface HorizontalProps extends InputLayoutBaseProps {
  center?: boolean;
  icon?: IconFunctionComponent;
}

function Horizontal({
  title,
  description,
  suffix,
  error,
  errorType = "error",
  center,
  icon,
  disabled,
  children,
  className,
}: HorizontalProps) {
  return (
    <View className={cn("w-full", disabled && "opacity-50", className)}>
      <View className={cn("flex-row", center ? "items-center" : "items-start")}>
        {icon ? (
          <Icon as={icon} size={16} className="mr-8 text-text-03" />
        ) : null}
        <View className="flex-1">
          <Label title={title} description={description} suffix={suffix} />
        </View>
        <View className="ml-8">{children}</View>
      </View>
      {error ? (
        <View className="mt-4">
          <InputErrorText type={errorType}>{error}</InputErrorText>
        </View>
      ) : null}
    </View>
  );
}

function InputDivider() {
  return (
    <View className="py-8">
      <Separator />
    </View>
  );
}

export interface InputPadderProps {
  children: ReactNode;
  className?: string;
}

function InputPadder({ children, className }: InputPadderProps) {
  return <View className={cn("w-full p-8", className)}>{children}</View>;
}

export {
  Label,
  InputErrorText,
  Vertical,
  Horizontal,
  InputDivider,
  InputPadder,
};
