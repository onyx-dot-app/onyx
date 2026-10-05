"use client";

import { useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import {
  Button,
  Card,
  Dropdown,
  Tag,
  Text,
  type DropdownItem,
  type DropdownView,
  type DropdownViews,
} from "@opal/components";
import { SvgEdit, SvgPlus, SvgUploadCloud, SvgX } from "@opal/icons";
import { SvgGithub } from "@opal/logos";
import useUserSkills from "@/hooks/useUserSkills";
import type { Skill } from "@/lib/skills/types";
import type { ExternalAppAdminResponse } from "@/app/craft/v1/apps/registry";

interface AssociatedSkillsEditorProps {
  app: ExternalAppAdminResponse;
  selectedSkillIds: string[];
  onChange: (skillIds: string[]) => void;
  onOpenSkill: (skillId: string) => void;
  onCreateSkill: () => void;
  onUploadSkill: () => void;
}

interface PendingUnlink {
  id: string;
  name: string;
}

export default function AssociatedSkillsEditor({
  app,
  selectedSkillIds,
  onChange,
  onOpenSkill,
  onCreateSkill,
  onUploadSkill,
}: AssociatedSkillsEditorProps) {
  const t = useTranslations("craft.apps.associatedSkills");
  const { data, isLoading } = useUserSkills();
  const [associateOpen, setAssociateOpen] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  // Where the lists portal to: a spot of our own inside the modal.
  const [container, setContainer] = useState<HTMLDivElement | null>(null);
  const [pendingPromotion, setPendingPromotion] = useState<Skill | null>(null);
  const [pendingUnlink, setPendingUnlink] = useState<PendingUnlink | null>(
    null
  );
  const customSkills = data?.customs ?? [];
  const customSkillById = useMemo(
    () => new Map(customSkills.map((skill) => [skill.id, skill])),
    [customSkills]
  );
  const selectedIds = useMemo(
    () => new Set(selectedSkillIds),
    [selectedSkillIds]
  );
  const selectedNames = useMemo(
    () =>
      new Set(
        selectedSkillIds.flatMap((skillId) => {
          const name =
            customSkillById.get(skillId)?.name ??
            app.associated_skills.find((skill) => skill.id === skillId)?.name;
          return name ? [name] : [];
        })
      ),
    [app.associated_skills, customSkillById, selectedSkillIds]
  );
  const selectableSkills = useMemo(
    () =>
      customSkills.filter(
        (skill) =>
          skill.user_permission === "OWNER" ||
          skill.user_permission === "EDITOR"
      ),
    [customSkills]
  );
  function unavailableReason(skill: Skill): string | null {
    if (skill.is_valid === false) {
      return t("unavailable.invalid");
    }
    if (
      skill.external_app !== null &&
      skill.external_app.external_app_id !== app.id
    ) {
      return t("unavailable.otherApp", { name: skill.external_app.name });
    }
    if (!selectedIds.has(skill.id) && selectedNames.has(skill.name)) {
      return t("unavailable.duplicateName", { name: skill.name });
    }
    return null;
  }
  function select(skill: Skill, views: DropdownViews) {
    if (unavailableReason(skill)) return;
    if (selectedIds.has(skill.id)) {
      setPendingUnlink(skill);
      setAssociateOpen(false);
      return;
    }
    if (skill.public_permission === null) {
      // The skill is private: promoting it is a page of its own.
      setPendingPromotion(skill);
      views.push("promote");
      return;
    }
    onChange([...selectedSkillIds, skill.id]);
    setAssociateOpen(false);
  }

  // The list's own search filters by name and description.
  const skillItems: DropdownItem[] = isLoading
    ? [
        {
          kind: "custom",
          id: "loading",
          disabled: true,
          pinned: true,
          render: ({ props }) => (
            <div {...props} className="px-2 py-1">
              <Text font="secondary-body" color="text-03">
                {t("loading.label")}
              </Text>
            </div>
          ),
        },
      ]
    : selectableSkills.length === 0
      ? [
          {
            kind: "custom",
            id: "empty",
            disabled: true,
            pinned: true,
            render: ({ props }) => (
              <div {...props} className="px-2 py-1">
                <Text font="secondary-body" color="text-03">
                  {t("empty.label")}
                </Text>
              </div>
            ),
          },
        ]
      : selectableSkills.map((skill) => {
          const disabledReason = unavailableReason(skill);
          return {
            kind: "option",
            value: String(skill.id),
            title: skill.name,
            keywords: [skill.description],
            description: disabledReason ?? skill.description,
            // Skill descriptions are user-authored, so cap the row rather
            // than let one grow the list.
            descriptionMaxLines: 1,
            disabled: disabledReason !== null,
          };
        });
  const promoteView: DropdownView = {
    items: [
      {
        kind: "custom",
        id: "promote",
        disabled: true,
        render: ({ props }) => (
          <div {...props} className="flex flex-col gap-1 px-2 py-1">
            <Text font="main-ui-action">
              {t("promote.title", { name: pendingPromotion?.name ?? "" })}
            </Text>
            <Text font="secondary-body" color="text-03">
              {t("promote.description")}
            </Text>
          </div>
        ),
      },
      {
        kind: "group",
        items: [
          {
            kind: "action",
            id: "promote-cancel",
            title: t("promote.cancelButton"),
            onSelect: (views) => {
              setPendingPromotion(null);
              views.pop();
            },
          },
          {
            kind: "action",
            id: "promote-confirm",
            title: t("promote.confirmButton"),
            onSelect: () => {
              if (pendingPromotion) {
                onChange([...selectedSkillIds, pendingPromotion.id]);
              }
              setPendingPromotion(null);
              setAssociateOpen(false);
            },
          },
        ],
      },
    ],
  };

  return (
    <div className="flex flex-col gap-3">
      <div ref={setContainer} />
      <div className="flex items-start justify-between gap-3">
        <div className="flex flex-col gap-0.5">
          <Text font="main-ui-action">{t("title")}</Text>
          <Text font="secondary-body" color="text-03">
            {t("description")}
          </Text>
        </div>
        <div className="flex shrink-0 gap-2">
          <Dropdown
            width={90}
            align="end"
            // Inside a modal, so the list portals into it: outside, the
            // modal would block clicks on it.
            container={container}
            open={associateOpen}
            onOpenChange={(open) => {
              setAssociateOpen(open);
              if (!open) setPendingPromotion(null);
            }}
          >
            <Dropdown.Trigger asChild>
              <Button prominence="secondary">{t("associateButton")}</Button>
            </Dropdown.Trigger>
            <Dropdown.Data
              label={t("associateButton")}
              search={{ placeholder: t("search.placeholder") }}
              values={new Set(Array.from(selectedIds, String))}
              onSelect={(option, views) => {
                const skill = customSkillById.get(option.value);
                if (skill) select(skill, views);
              }}
              items={skillItems}
              views={{ promote: promoteView }}
            />
          </Dropdown>
          <Dropdown
            container={container}
            open={createOpen}
            onOpenChange={setCreateOpen}
          >
            <Dropdown.Trigger asChild>
              <Button icon={SvgPlus}>{t("createSkillButton")}</Button>
            </Dropdown.Trigger>
            <Dropdown.Data
              label={t("createSkillButton")}
              items={[
                {
                  kind: "action",
                  id: "scratch",
                  icon: SvgEdit,
                  title: t("create.scratch.label"),
                  description: t("create.scratch.description"),
                  onSelect: () => onCreateSkill(),
                },
                {
                  kind: "action",
                  id: "upload",
                  icon: SvgUploadCloud,
                  title: t("create.upload.label"),
                  description: t("create.upload.description"),
                  onSelect: () => onUploadSkill(),
                },
                {
                  kind: "action",
                  id: "github",
                  icon: SvgGithub,
                  title: t("create.github.label"),
                  description: t("create.github.description"),
                  disabled: true,
                  onSelect: () => {},
                },
              ]}
            />
          </Dropdown>
        </div>
      </div>

      {selectedSkillIds.length === 0 ? (
        <Card border="solid" rounding={4} padding={2}>
          <Text font="secondary-body" color="text-03">
            {t("noneAssociated.label")}
          </Text>
        </Card>
      ) : (
        <Card border="solid" rounding={2} padding={0}>
          <div className="flex max-h-48 flex-col divide-y divide-border-01 overflow-y-auto overscroll-contain">
            {selectedSkillIds.map((skillId) => {
              const skill = customSkillById.get(skillId);
              const canEdit =
                skill?.user_permission === "OWNER" ||
                skill?.user_permission === "EDITOR";
              const summary = app.associated_skills.find(
                (candidate) => candidate.id === skillId
              );
              const name = skill?.name ?? summary?.name;
              if (!name) return null;
              if (pendingUnlink?.id === skillId) {
                return (
                  <div
                    key={skillId}
                    className="flex min-h-9 items-center gap-2 px-2 py-1"
                  >
                    <div className="min-w-0 flex-1">
                      <Text font="secondary-body">
                        {t("unlink.confirm", { name: pendingUnlink.name })}
                      </Text>
                    </div>
                    <Button
                      size="md"
                      prominence="secondary"
                      onClick={() => setPendingUnlink(null)}
                    >
                      {t("unlink.cancelButton")}
                    </Button>
                    <Button
                      size="md"
                      onClick={() => {
                        onChange(
                          selectedSkillIds.filter(
                            (selectedSkillId) =>
                              selectedSkillId !== pendingUnlink.id
                          )
                        );
                        setPendingUnlink(null);
                      }}
                    >
                      {t("unlink.button")}
                    </Button>
                  </div>
                );
              }
              return (
                <div
                  key={skillId}
                  className="flex min-h-9 items-center gap-1 px-2 py-1"
                >
                  <div className="min-w-0 flex-1">
                    <Text font="main-ui-action">{name}</Text>
                  </div>
                  {(skill?.is_valid ?? summary?.is_valid) === false && (
                    <Tag title={t("invalidTag")} color="amber" />
                  )}
                  <Button
                    size="md"
                    prominence="tertiary"
                    onClick={() => onOpenSkill(skillId)}
                  >
                    {canEdit ? t("editButton") : t("viewButton")}
                  </Button>
                  <Button
                    size="md"
                    prominence="tertiary"
                    icon={SvgX}
                    aria-label={t("unlinkAriaLabel", { name })}
                    onClick={() => {
                      setPendingUnlink({ id: skillId, name });
                    }}
                  />
                </div>
              );
            })}
          </div>
        </Card>
      )}
    </div>
  );
}
