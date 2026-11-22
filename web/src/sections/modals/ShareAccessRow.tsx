"use client";

import { useMemo } from "react";

import { Card, IconContainer } from "@opal/components";
import { ContentAction, Section } from "@opal/layouts";
import type { IconFunctionComponent, RichStr } from "@opal/types";

interface PermissionColumnsProps {
  rightChildren?: React.ReactNode;
  trailing?: React.ReactNode;
}

// A fixed 10rem permission column, so every row's permission label starts at
// the same x, plus the far-right slot.
function PermissionColumns({
  rightChildren,
  trailing,
}: PermissionColumnsProps) {
  return (
    <Section
      flexDirection="row"
      alignItems="center"
      width="auto"
      height="auto"
      gap={0}
      shrink={false}
    >
      <Section
        flexDirection="row"
        justifyContent="start"
        alignItems="center"
        width={10}
        height="auto"
      >
        {rightChildren}
      </Section>
      {trailing}
    </Section>
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
      avatarInitial
        ? function ShareRowAvatar() {
            return <IconContainer avatar="user" name={avatarInitial} />;
          }
        : avatarIcon
          ? function ShareRowAvatarIcon() {
              return <IconContainer avatar="icon" icon={avatarIcon} />;
            }
          : icon,
    [avatarInitial, avatarIcon, icon]
  );

  return (
    <Card color="background-tint-01" rounding={3} padding={0.5}>
      {titleSlot ? (
        // ContentAction can't host a component title, so the scope row
        // (a dropdown in the title position) lays out its own row.
        <Section
          flexDirection="row"
          justifyContent="between"
          alignItems="center"
          height="auto"
          gap={2}
          padding={0.5}
        >
          <Section
            flexDirection="row"
            justifyContent="start"
            alignItems="center"
            height="auto"
            gap={2}
            grow={1}
          >
            <IconContainer icon={LeadingIcon} />
            {titleSlot}
          </Section>
          <PermissionColumns
            rightChildren={rightChildren}
            trailing={trailing}
          />
        </Section>
      ) : (
        <ContentAction
          font="main-ui-action"
          responsive
          description={description}
          icon={LeadingIcon}
          padding={1}
          rightChildren={
            <PermissionColumns
              rightChildren={rightChildren}
              trailing={trailing}
            />
          }
          title={title ?? ""}
        />
      )}
    </Card>
  );
}
