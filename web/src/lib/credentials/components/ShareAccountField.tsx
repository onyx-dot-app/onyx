"use client";

import { useTranslations } from "next-intl";
import { useFormikContext } from "formik";
import {
  InputMultiSelect,
  InputSingleSelect,
  type TagItem,
} from "@opal/components";
import { InputHorizontal, Section } from "@opal/layouts";
import { Disabled } from "@opal/core";
import { SvgLock, SvgUserManage, SvgUsers } from "@opal/icons";
import { useUserGroups } from "@/lib/hooks";

/** Who may reuse a new credential. */
export type ShareAudience = "admins" | "adminsAndGroups" | "onlyMe";

export const DEFAULT_SHARE_AUDIENCE: ShareAudience = "admins";

/** The form values the field reads and writes. */
export interface ShareAccountFormValues {
  share: ShareAudience;
  /** User groups that may reuse the credential, with `adminsAndGroups`. */
  groups: number[];
}

function isShareAudience(value: string): value is ShareAudience {
  return (
    value === "admins" || value === "adminsAndGroups" || value === "onlyMe"
  );
}

/** The credential payload's sharing fields for the chosen audience. */
export function shareAccountPayload({ share, groups }: ShareAccountFormValues) {
  return {
    admin_public: share !== "onlyMe",
    groups: share === "adminsAndGroups" ? groups : [],
  };
}

// The tag id of the admins chip; group tags use their numeric ids.
const ADMINS_TAG_ID = "admins";

interface ShareAccountFieldProps {
  /** Dims and locks the field, as while the account's fields are invalid. */
  disabled: boolean;
}

/**
 * Who may reuse the new credential: admins (the default), admins and named
 * user groups, or only its creator. With groups, a picker below lists them
 * after a fixed admins chip, since admins keep access either way.
 */
export function ShareAccountField({ disabled }: ShareAccountFieldProps) {
  const t = useTranslations("admin.credentials.create.share");
  const tGroups = useTranslations("common.groupsMultiSelect");
  const { values, setFieldValue } = useFormikContext<ShareAccountFormValues>();
  const { data: userGroups } = useUserGroups();

  const groupNames = new Map(
    (userGroups ?? []).map((group) => [group.id, group.name])
  );
  const groupTags: TagItem[] = values.groups.flatMap((id) => {
    const name = groupNames.get(id);
    return name === undefined ? [] : [{ id: String(id), label: name }];
  });
  const adminsTag: TagItem = {
    id: ADMINS_TAG_ID,
    label: t("admins.label"),
    icon: SvgUserManage,
    locked: true,
  };

  return (
    <Disabled disabled={disabled}>
      <Section alignItems="stretch" gap={4}>
        <InputHorizontal
          // A bare label (no htmlFor) hands a click on the title to the select
          // inside it, which opens the list.
          withLabel
          title={t("title")}
          description={t("description")}
          center
        >
          <InputSingleSelect
            value={values.share}
            onValueChange={(next) => {
              if (isShareAudience(next)) setFieldValue("share", next);
            }}
            defaultOption={DEFAULT_SHARE_AUDIENCE}
            placeholder={t("title")}
            disabled={disabled}
            options={[
              {
                value: "admins",
                title: t("admins.label"),
                suffix: t("admins.suffix"),
                description: t("admins.description"),
                icon: SvgUserManage,
              },
              {
                value: "adminsAndGroups",
                title: t("adminsAndGroups.label"),
                description: t("adminsAndGroups.description"),
                icon: SvgUsers,
              },
              {
                options: [
                  { value: "onlyMe", title: t("onlyMe.label"), icon: SvgLock },
                ],
              },
            ]}
          />
        </InputHorizontal>

        {values.share === "adminsAndGroups" && (
          <InputMultiSelect
            tags={[adminsTag, ...groupTags]}
            options={(userGroups ?? []).map((group) => ({
              value: String(group.id),
              title: group.name,
              icon: SvgUsers,
            }))}
            onSelectOption={(option) =>
              setFieldValue("groups", [...values.groups, Number(option.value)])
            }
            onRemoveTag={(id) =>
              setFieldValue(
                "groups",
                values.groups.filter((group) => String(group) !== id)
              )
            }
            placeholder={tGroups("userGroups.label")}
            disabled={disabled}
          />
        )}
      </Section>
    </Disabled>
  );
}
