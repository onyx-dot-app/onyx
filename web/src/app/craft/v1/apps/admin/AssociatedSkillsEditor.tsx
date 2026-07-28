"use client";

import { useMemo, useState } from "react";
import {
  Button,
  Card,
  InputTypeIn,
  Popover,
  Tag,
  Text,
} from "@opal/components";
import { SvgCheck, SvgEdit, SvgPlus, SvgUploadCloud, SvgX } from "@opal/icons";
import { SvgGithub } from "@opal/logos";
import useUserSkills from "@/hooks/useUserSkills";
import type { Skill } from "@/lib/skills/types";
import type { ExternalAppAdminResponse } from "@/app/craft/v1/apps/registry";
import LineItem from "@/refresh-components/buttons/LineItem";

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
  const { data, isLoading } = useUserSkills();
  const [query, setQuery] = useState("");
  const [associateOpen, setAssociateOpen] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
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
  const selectableSkills = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();
    return customSkills
      .filter(
        (skill) =>
          skill.user_permission === "OWNER" ||
          skill.user_permission === "EDITOR"
      )
      .filter(
        (skill) =>
          normalizedQuery.length === 0 ||
          skill.name.toLowerCase().includes(normalizedQuery) ||
          skill.description.toLowerCase().includes(normalizedQuery)
      );
  }, [app.id, customSkills, query]);
  function unavailableReason(skill: Skill): string | null {
    if (skill.is_valid === false) {
      return "Invalid skill — fix it before associating.";
    }
    if (
      skill.external_app !== null &&
      skill.external_app.external_app_id !== app.id
    ) {
      return `Already associated with app “${skill.external_app.name}”.`;
    }
    if (!selectedIds.has(skill.id) && selectedNames.has(skill.name)) {
      return `A skill named “${skill.name}” is already associated.`;
    }
    return null;
  }
  function select(skill: Skill) {
    if (unavailableReason(skill)) return;
    if (selectedIds.has(skill.id)) {
      setPendingUnlink(skill);
      setAssociateOpen(false);
      return;
    }
    if (skill.public_permission === null) {
      setPendingPromotion(skill);
      return;
    }
    onChange([...selectedSkillIds, skill.id]);
    setAssociateOpen(false);
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-start justify-between gap-3">
        <div className="flex flex-col gap-0.5">
          <Text font="main-ui-action">Associated skills</Text>
          <Text font="secondary-body" color="text-03">
            Skills give Craft instructions for using this app. They are
            organization-wide; users may need to enable all of them for the app
            to work correctly.
          </Text>
        </div>
        <div className="flex shrink-0 gap-2">
          <Popover
            modal
            open={associateOpen}
            onOpenChange={(open) => {
              setAssociateOpen(open);
              if (!open) setPendingPromotion(null);
            }}
          >
            <Popover.Trigger asChild>
              <Button prominence="secondary">Associate existing</Button>
            </Popover.Trigger>
            <Popover.Content align="end" sideOffset={4} width="xl">
              <div className="flex max-h-[min(20rem,calc(var(--radix-popover-content-available-height)-0.5rem))] flex-col gap-2 overflow-hidden p-2">
                <InputTypeIn
                  searchIcon
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  placeholder="Search editable skills..."
                  variant="internal"
                />
                <div className="flex min-h-0 flex-col gap-1 overflow-y-auto overscroll-contain">
                  {isLoading ? (
                    <Text font="secondary-body" color="text-03">
                      Loading skills…
                    </Text>
                  ) : selectableSkills.length === 0 ? (
                    <Text font="secondary-body" color="text-03">
                      No editable skills found.
                    </Text>
                  ) : (
                    selectableSkills.map((skill) => {
                      const disabledReason = unavailableReason(skill);
                      return (
                        <LineItem
                          key={skill.id}
                          onClick={() => select(skill)}
                          description={disabledReason ?? skill.description}
                          disabled={disabledReason !== null}
                          selected={selectedIds.has(skill.id)}
                          rightChildren={
                            selectedIds.has(skill.id) ? (
                              <SvgCheck className="size-4 stroke-action-link-05" />
                            ) : undefined
                          }
                          aria-label={`Associate ${skill.name}`}
                        >
                          {skill.name}
                        </LineItem>
                      );
                    })
                  )}
                </div>
                {pendingPromotion && (
                  <div className="flex flex-col gap-2 border-t border-border-01 pt-2">
                    <Text font="main-ui-action">
                      {`Make “${pendingPromotion.name}” organization-wide?`}
                    </Text>
                    <Text font="secondary-body" color="text-03">
                      App-associated skills must be available to everyone. This
                      change is applied when you save the app.
                    </Text>
                    <div className="flex justify-end gap-2">
                      <Button
                        prominence="secondary"
                        onClick={() => setPendingPromotion(null)}
                      >
                        Cancel
                      </Button>
                      <Button
                        onClick={() => {
                          onChange([...selectedSkillIds, pendingPromotion.id]);
                          setPendingPromotion(null);
                          setAssociateOpen(false);
                        }}
                      >
                        Make organization-wide
                      </Button>
                    </div>
                  </div>
                )}
              </div>
            </Popover.Content>
          </Popover>
          <Popover modal open={createOpen} onOpenChange={setCreateOpen}>
            <Popover.Trigger asChild>
              <Button icon={SvgPlus}>Create skill</Button>
            </Popover.Trigger>
            <Popover.Content align="end" sideOffset={4} width="lg">
              <Popover.Menu>
                <LineItem
                  icon={SvgEdit}
                  onClick={() => {
                    setCreateOpen(false);
                    onCreateSkill();
                  }}
                  description="Write instructions and add supporting files."
                  wrapDescription
                >
                  Start from scratch
                </LineItem>
                <LineItem
                  icon={SvgUploadCloud}
                  onClick={() => {
                    setCreateOpen(false);
                    onUploadSkill();
                  }}
                  description="Import a SKILL.md file, ZIP file, or skill folder."
                  wrapDescription
                >
                  Upload a skill
                </LineItem>
                <LineItem
                  icon={SvgGithub}
                  disabled
                  description="If your skills are in GitHub, import them on the Skills page first, then associate them with this app."
                  wrapDescription
                >
                  Import from GitHub
                </LineItem>
              </Popover.Menu>
            </Popover.Content>
          </Popover>
        </div>
      </div>

      {selectedSkillIds.length === 0 ? (
        <Card border="solid" rounding="lg" padding="sm">
          <Text font="secondary-body" color="text-03">
            No skills are associated yet. This app can still be saved and used
            without one.
          </Text>
        </Card>
      ) : (
        <Card border="solid" rounding="sm" padding="fit">
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
                        {`Unlink “${pendingUnlink.name}” from this app?`}
                      </Text>
                    </div>
                    <Button
                      size="md"
                      prominence="secondary"
                      onClick={() => setPendingUnlink(null)}
                    >
                      Cancel
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
                      Unlink
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
                    <Tag title="Invalid" color="amber" />
                  )}
                  <Button
                    size="md"
                    prominence="tertiary"
                    onClick={() => onOpenSkill(skillId)}
                  >
                    {canEdit ? "Edit" : "View"}
                  </Button>
                  <Button
                    size="md"
                    prominence="tertiary"
                    icon={SvgX}
                    aria-label={`Unlink ${name}`}
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
