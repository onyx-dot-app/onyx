import type { ReactNode } from "react";
import { ScrollView, View, type ScrollViewProps } from "react-native";

import { cn } from "@/lib/utils";
import { Content } from "@/components/ui/content";
import { Separator } from "@/components/ui/separator";
import type { IconFunctionComponent } from "@/icons/types";

// RN port of Opal `SettingsLayouts`. Sticky + scroll-shadow (web: only when Header has
// `rightChildren`) is intentionally omitted. Web's `width` variants are dropped — a phone
// is always narrower than the smallest cap; back-nav is the screen's chrome / OS gesture.

interface SettingsRootProps {
  children: ReactNode;
  className?: string;
  // Forwarded so a search field's keyboard doesn't swallow taps on the list below.
  keyboardShouldPersistTaps?: ScrollViewProps["keyboardShouldPersistTaps"];
}

function SettingsRoot({
  children,
  className,
  keyboardShouldPersistTaps,
}: SettingsRootProps) {
  return (
    <ScrollView
      className={cn("flex-1", className)}
      showsVerticalScrollIndicator={false}
      keyboardShouldPersistTaps={keyboardShouldPersistTaps}
    >
      {children}
    </ScrollView>
  );
}

interface SettingsHeaderProps {
  icon: IconFunctionComponent;
  title: string;
  description?: string;
  children?: ReactNode;
  rightChildren?: ReactNode;
  divider?: boolean;
}

function SettingsHeader({
  icon,
  title,
  description,
  children,
  rightChildren,
  divider,
}: SettingsHeaderProps) {
  return (
    <View className="w-full">
      <View className="h-16" />

      <View className="gap-24 px-16">
        <View className="w-full flex-row items-start justify-between">
          <Content
            icon={icon}
            title={title}
            description={description}
            className="flex-1"
          />
          {rightChildren ? <View>{rightChildren}</View> : null}
        </View>

        {children}
      </View>

      {divider ? (
        <>
          <View className="h-24" />
          <View className="px-16">
            <Separator />
          </View>
        </>
      ) : (
        <View className="h-8" />
      )}
    </View>
  );
}

interface SettingsBodyProps {
  children: ReactNode;
  className?: string;
}

function SettingsBody({ children, className }: SettingsBodyProps) {
  return (
    <View className={cn("w-full flex-col gap-32 px-16 pb-72 pt-24", className)}>
      {children}
    </View>
  );
}

export const SettingsLayout = {
  Root: SettingsRoot,
  Header: SettingsHeader,
  Body: SettingsBody,
};

export type { SettingsRootProps, SettingsHeaderProps, SettingsBodyProps };
