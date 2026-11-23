"use client";

import React, { useState, useEffect } from "react";
import { useTranslations } from "next-intl";
import { IconContainer, InputTypeIn, SelectCard } from "@opal/components";
import {
  buildUserProfileImageUrl,
  getUserAddressedName,
  getUserEmail,
  getUserInitials,
  updateUserPersonalization,
} from "@/lib/users/svc";
import { useUser } from "@/providers/UserProvider";
import type { UserPersonalization } from "@/lib/types";
import { Button } from "@opal/components";
import { cn } from "@opal/utils";
import { SvgCheckCircle, SvgEdit, SvgUser, SvgX } from "@opal/icons";
import { ContentAction, InputHorizontal, Section, toast } from "@opal/layouts";
import { Hoverable } from "@opal/core";
import { useSettings } from "@/lib/settings/hooks";

export default function NonAdminStep() {
  const t = useTranslations("onboarding");
  const { appName } = useSettings();
  const { user, refreshUser } = useUser();
  const [name, setName] = useState("");
  const [showHeader, setShowHeader] = useState(false);
  const [isEditing, setIsEditing] = useState(true);
  const [savedName, setSavedName] = useState("");

  const addressedName = getUserAddressedName(user);

  // Initialize name from user if available
  useEffect(() => {
    if (addressedName && !savedName) {
      setSavedName(addressedName);
      setIsEditing(false);
    }
  }, [addressedName, savedName]);

  const containerClasses = cn(
    "flex items-center justify-between w-full p-3 bg-background-tint-00 rounded-16 border border-border-01 mb-4"
  );

  const handleEdit = () => {
    setIsEditing(true);
    setName(savedName);
  };

  const handleSave = () => {
    const personalization: Partial<UserPersonalization> = {
      preferred_name: name,
    };
    // Admin views, search and sharing show the full name, so onboarding
    // fills it when the user has none.
    if (!user?.personalization?.name) personalization.name = name;
    updateUserPersonalization(personalization)
      .then((response) => {
        if (!response.ok) {
          throw new Error(`Saving the name failed: ${response.status}`);
        }
        setSavedName(name);
        setShowHeader(true);
        setIsEditing(false);
        // Don't call refreshUser() here — it would cause OnboardingFlow to
        // unmount this component (since the preferred name becomes set),
        // hiding the confirmation banner before the user sees it.
        // refreshUser() is called in handleDismissConfirmation instead.
      })
      .catch((error) => {
        toast.error(t("nonAdminStep.toasts.saveNameFailed"));
        console.error(error);
      });
  };

  const handleDismissConfirmation = () => {
    setShowHeader(false);
    refreshUser();
  };

  return (
    <>
      {showHeader && (
        <div
          className="flex items-center justify-between w-full min-h-11 py-1 ps-3 pe-2 bg-background-tint-00 rounded-16 shadow-box-01 mb-2"
          aria-label="non-admin-confirmation"
        >
          <ContentAction
            font="main-ui-body"
            icon={({ className, ...props }) => (
              <SvgCheckCircle
                className={cn(className, "stroke-status-success-05")}
                {...props}
              />
            )}
            title={t("nonAdminStep.confirmation.title")}
            titleColor="text-03"
            padding={0}
            rightChildren={
              <Button
                prominence="tertiary"
                size="sm"
                icon={SvgX}
                onClick={handleDismissConfirmation}
              />
            }
          />
        </div>
      )}
      {isEditing ? (
        <div
          className={containerClasses}
          role="group"
          aria-label="non-admin-name-prompt"
        >
          {/* Save sits outside the input's label: a label must not contain a
              second control. */}
          <Section
            flexDirection="row"
            justifyContent="start"
            alignItems="center"
            gap={2}
            height="auto"
          >
            <InputHorizontal
              withLabel
              fillInput
              responsive
              icon={SvgUser}
              title={t("nameStep.title", { appName })}
              description={t("nameStep.description")}
            >
              <InputTypeIn
                placeholder={t("nameStep.input.placeholder")}
                value={name || ""}
                onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
                  setName(e.target.value)
                }
                onKeyDown={(e) => {
                  if (e.key === "Enter" && name && name.trim().length > 0) {
                    e.preventDefault();
                    handleSave();
                  }
                }}
              />
            </InputHorizontal>
            <Button disabled={name === ""} onClick={handleSave}>
              {t("nonAdminStep.save.label")}
            </Button>
          </Section>
        </div>
      ) : (
        <Hoverable.Root group="nonAdminName" width="full">
          <SelectCard
            state="empty"
            padding={2}
            rounding={4}
            onClick={handleEdit}
            aria-label={t("nameStep.edit.ariaLabel")}
          >
            <div className="pl-1">
              <ContentAction
                font="main-ui-action"
                icon={() => (
                  <IconContainer
                    size="secondary"
                    avatar="user"
                    initials={getUserInitials(
                      savedName || null,
                      getUserEmail(user)
                    )}
                    src={buildUserProfileImageUrl(user)}
                  />
                )}
                title={savedName}
                padding={0}
                center
                rightChildren={
                  <Section
                    flexDirection="row"
                    alignItems="center"
                    gap={1}
                    width="fit"
                    height="auto"
                  >
                    <Hoverable.Item
                      group="nonAdminName"
                      variant="appear-on-hover"
                    >
                      <Button
                        prominence="tertiary"
                        size="md"
                        icon={SvgEdit}
                        tooltip={t("nameStep.edit.tooltip")}
                      />
                    </Hoverable.Item>
                    <Section padding={1} width="fit" height="auto">
                      <IconContainer
                        icon={({ className, ...props }) => (
                          <SvgCheckCircle
                            className={cn(
                              className,
                              "stroke-status-success-05"
                            )}
                            {...props}
                          />
                        )}
                      />
                    </Section>
                  </Section>
                }
              />
            </div>
          </SelectCard>
        </Hoverable.Root>
      )}
    </>
  );
}
