/* Content */
export {
  Content,
  type ContentProps,
  type SizePreset,
  type ContentVariant,
} from "@opal/layouts/content/components";

/* ContentAction */
export {
  ContentAction,
  type ContentActionProps,
} from "@opal/layouts/content-action/components";

/* Card */
export { Card, type CardHeaderProps } from "@opal/layouts/cards/components";

/* Input */
export {
  Label,
  type LabelProps,
  Vertical as InputVertical,
  type VerticalProps as InputVerticalProps,
  Horizontal as InputHorizontal,
  type HorizontalProps as InputHorizontalProps,
  InputErrorText,
  type InputErrorTextProps,
  type InputErrorType,
  InputDivider,
  InputPadder,
  type InputPadderProps,
} from "@opal/layouts/inputs/components";

/* IllustrationContent */
export {
  IllustrationContent,
  type IllustrationContentProps,
} from "@opal/layouts/illustration-content/components";

/* Section (general layout primitive) */
export {
  Section,
  widthClassmap,
  heightClassmap,
  type SectionProps,
  type FlexDirection,
  type JustifyContent,
  type AlignItems,
  type Length,
} from "@opal/layouts/general/components";

/* SettingsLayouts */
export * as SettingsLayouts from "@opal/layouts/settings/components";
export type { SettingsHeaderProps } from "@opal/layouts/settings/components";

/* RootLayout */
export * as RootLayout from "@opal/layouts/root/components";
export {
  useSidebarState,
  SidebarStateProvider,
  RootLayoutRightPanelSlotContext,
} from "@opal/layouts/root/components";
export type {
  SidebarStateProviderProps,
  RightPanelSlotSetter,
} from "@opal/layouts/root/components";

/* SidebarLayouts */
export * as SidebarLayouts from "@opal/layouts/sidebar/components";
export { type SidebarRootProps } from "@opal/layouts/sidebar/components";

/* AuthLayouts */
export * as AuthLayouts from "@opal/layouts/auth/components";
export type {
  CardProps as AuthCardProps,
  FieldsProps as AuthFieldsProps,
  SubmitProps as AuthSubmitProps,
  SubmitLabel as AuthSubmitLabel,
} from "@opal/layouts/auth/components";

/* TagList */
export { TagList, type TagListProps } from "@opal/layouts/tag-list/components";

/* Toast */
export {
  ToastProvider,
  type ToastProviderProps,
} from "@opal/layouts/toast/components";
export {
  toast,
  useToast,
  useToastFromQuery,
  MAX_VISIBLE_TOASTS,
  type Toast,
  type ToastLevel,
  type ToastOptions,
} from "@opal/layouts/toast/store";
