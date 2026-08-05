"use client";

import { useMemo } from "react";

import { Text } from "@opal/components";
import { ContentAction } from "@opal/layouts";
import type { IconFunctionComponent, RichStr } from "@opal/types";

interface ShareAvatarProps {
  initial?: string;
  icon?: IconFunctionComponent;
}

// No opal avatar primitive exists yet — the mock's dark initial/glyph circle
// is the one hand-built piece in this file
function ShareAvatar({ initial, icon: Icon }: ShareAvatarProps) {
  return (
    <div className="flex h-7 w-7 items-center justify-center rounded-full bg-background-neutral-inverted-00">
      {Icon ? (
        <Icon size={12} className="stroke-text-inverted-05" aria-hidden />
      ) : (
        <Text font="secondary-action" color="text-inverted-05">
          {initial}
        </Text>
      )}
    </div>
  );
}

interface PermissionColumnsProps {
  rightChildren?: React.ReactNode;
  trailing?: React.ReactNode;
}

// Fixed 160px left-aligned permission column (mock: Column/Medium) so every
// row's permission label starts at the same x, plus the far-right slot
function PermissionColumns({
  rightChildren,
  trailing,
}: PermissionColumnsProps) {
  return (
    <div className="flex shrink-0 items-center">
      <div className="flex w-40 items-center justify-start">
        {rightChildren}
      </div>
      {trailing}
    </div>
  );
}

export interface ShareAccessRowProps {
  icon: IconFunctionComponent;
  /** Initial rendered in a dark avatar circle; omitted → the bare icon */
  avatarInitial?: string;
  /** Icon rendered inside a dark avatar circle (groups, service accounts) */
  avatarIcon?: IconFunctionComponent;
  title?: string | RichStr;
  /** Replaces the title text (e.g. the scope dropdown trigger) */
  titleSlot?: React.ReactNode;
  description?: string | RichStr;
  rightChildren?: React.ReactNode;
  /** Far-right slot past the permission column (e.g. the owner swap icon) */
  trailing?: React.ReactNode;
}

export function ShareAccessRow({
  icon,
  avatarInitial,
  avatarIcon,
  title,
  titleSlot,
  description,
  rightChildren,
  trailing,
}: ShareAccessRowProps) {
  // Stable identity: a fresh function each render makes ContentAction remount
  // the icon subtree instead of updating it.
  const LeadingIcon: IconFunctionComponent = useMemo(
    () =>
      avatarInitial || avatarIcon
        ? function ShareRowAvatarIcon() {
            return <ShareAvatar initial={avatarInitial} icon={avatarIcon} />;
          }
        : icon,
    [avatarInitial, avatarIcon, icon]
  );

  // ContentAction can't host a component title — the scope row (dropdown in
  // the title position) keeps a layout-only flex of opal children
  if (titleSlot) {
    return (
      <div className="flex min-h-11 w-full items-center justify-between gap-2 rounded-12 bg-background-tint-01 px-1 py-1">
        <div className="flex min-w-0 flex-1 items-center gap-2">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center">
            <LeadingIcon size={16} className="stroke-text-03" aria-hidden />
          </div>
          {titleSlot}
        </div>
        <PermissionColumns rightChildren={rightChildren} trailing={trailing} />
      </div>
    );
  }

  return (
    <div className="min-h-11 w-full rounded-12 bg-background-tint-01 px-1">
      <ContentAction
        description={description}
        icon={LeadingIcon}
        padding="sm"
        rightChildren={
          <PermissionColumns
            rightChildren={rightChildren}
            trailing={trailing}
          />
        }
        sizePreset="main-ui"
        title={title ?? ""}
        variant="section"
      />
    </div>
  );
}
