"use client";

import { useTranslations } from "next-intl";
import { getIn, useFormikContext } from "formik";
import {
  InputMultiSelect,
  InputSingleSelect,
  type TagItem,
} from "@opal/components";
import { InputHorizontal, Section } from "@opal/layouts";
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

/** The audience and groups a saved credential is shared with. */
export function shareAccountValues(credential: {
  admin_public: boolean;
  groups?: number[];
}): ShareAccountFormValues {
  const groups: number[] = credential.groups ?? [];
  return {
    share: !credential.admin_public
      ? "onlyMe"
      : groups.length > 0
        ? "adminsAndGroups"
        : "admins",
    groups,
  };
}

interface ShareAccountSelectProps {
  value: ShareAccountFormValues;
  onChange: (next: ShareAccountFormValues) => void;
  /** Locks the selects. The caller wraps them in `Disabled` for the look. */
  disabled: boolean;
}

/**
 * Who may reuse a credential: admins (the default), admins and named user
 * groups, or only its creator. With groups, a picker below lists them after
 * a fixed admins chip, since admins keep access either way.
 */
export function ShareAccountSelect({
  value,
  onChange,
  disabled,
}: ShareAccountSelectProps) {
  const t = useTranslations("admin.credentials.create.share");
  const tGroups = useTranslations("common.groupsMultiSelect");
  const { data: userGroups } = useUserGroups();

  const groupNames = new Map(
    (userGroups ?? []).map((group) => [group.id, group.name])
  );
  const groupTags: TagItem[] = value.groups.flatMap((id) => {
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
          value={value.share}
          onValueChange={(next) => {
            if (isShareAudience(next)) onChange({ ...value, share: next });
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

      {value.share === "adminsAndGroups" && (
        <InputMultiSelect
          tags={[adminsTag, ...groupTags]}
          options={(userGroups ?? []).map((group) => ({
            value: String(group.id),
            title: group.name,
            icon: SvgUsers,
          }))}
          onSelectOption={(option) =>
            onChange({
              ...value,
              groups: [...value.groups, Number(option.value)],
            })
          }
          onRemoveTag={(id) =>
            onChange({
              ...value,
              groups: value.groups.filter((group) => String(group) !== id),
            })
          }
          placeholder={tGroups("userGroups.label")}
          disabled={disabled}
        />
      )}
    </Section>
  );
}

interface ShareAccountFieldProps {
  /** The Formik path `share` and `groups` live under, e.g. `new_account`. */
  namePrefix?: string;
  /**
   * Locks the selects, as while the account's fields are invalid. The caller
   * wraps the field in `Disabled` for the dimmed look.
   */
  disabled: boolean;
}

/** {@link ShareAccountSelect} bound to a Formik form's values. */
export function ShareAccountField({
  disabled,
  namePrefix,
}: ShareAccountFieldProps) {
  const { values: formValues, setFieldValue } =
    useFormikContext<ShareAccountFormValues>();
  const values: ShareAccountFormValues = namePrefix
    ? getIn(formValues, namePrefix)
    : formValues;
  const path = (field: keyof ShareAccountFormValues): string =>
    namePrefix ? `${namePrefix}.${field}` : field;

  return (
    <ShareAccountSelect
      value={values}
      onChange={(next) => {
        if (next.share !== values.share)
          setFieldValue(path("share"), next.share);
        if (next.groups !== values.groups)
          setFieldValue(path("groups"), next.groups);
      }}
      disabled={disabled}
    />
  );
}
