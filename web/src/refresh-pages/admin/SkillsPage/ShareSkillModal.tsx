"use client";

import { useEffect, useState } from "react";
import { Button } from "@opal/components";
import { SvgShare } from "@opal/icons";
import Modal from "@/refresh-components/Modal";
import { Section } from "@/layouts/general-layouts";
import SkillSharePicker from "@/refresh-pages/admin/SkillsPage/SkillSharePicker";
import { patchCustomSkill, replaceCustomSkillGrants } from "@/lib/skills/api";
import { toast } from "@/hooks/useToast";
import type { CustomSkill } from "@/refresh-pages/admin/SkillsPage/interfaces";

interface ShareSkillModalProps {
  skill: CustomSkill | null;
  open: boolean;
  onClose: () => void;
  /** Called after a successful save so callers can revalidate. */
  onSaved: () => void;
}

export default function ShareSkillModal({
  skill,
  open,
  onClose,
  onSaved,
}: ShareSkillModalProps) {
  const [isPublic, setIsPublic] = useState(skill?.is_public ?? false);
  const [groupIds, setGroupIds] = useState<number[]>(
    skill?.granted_group_ids ?? []
  );
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (skill) {
      setIsPublic(skill.is_public);
      setGroupIds(skill.granted_group_ids);
    }
  }, [skill]);

  if (!skill) return null;

  async function handleSave() {
    if (!skill) return;
    setSaving(true);
    try {
      // Org-wide skills don't keep group grants — the visibility filter
      // ignores them, so clear the list to keep the DB tidy.
      const targetGroups = isPublic ? [] : groupIds;
      const groupsChanged =
        targetGroups.length !== skill.granted_group_ids.length ||
        targetGroups.some((id) => !skill.granted_group_ids.includes(id));
      const isPublicChanged = isPublic !== skill.is_public;

      // Order operations so a partial failure can only widen access, never
      // narrow it. When making access broader (flipping `is_public` to true),
      // apply the org-wide flip first and clean up grants after. When
      // narrowing, write grants first so the skill remains reachable via
      // groups even if the `is_public` patch later fails.
      if (isPublic) {
        if (isPublicChanged) {
          await patchCustomSkill(skill.id, { is_public: isPublic });
        }
        if (groupsChanged) {
          await replaceCustomSkillGrants(skill.id, targetGroups);
        }
      } else {
        if (groupsChanged) {
          await replaceCustomSkillGrants(skill.id, targetGroups);
        }
        if (isPublicChanged) {
          await patchCustomSkill(skill.id, { is_public: isPublic });
        }
      }

      toast.success(`Updated "${skill.name}" visibility`);
      onSaved();
      onClose();
    } catch (err) {
      console.error("Failed to update skill visibility", err);
      // Refresh parent data even on failure so the next open reflects the
      // partially-applied server state rather than the stale `skill` prop.
      onSaved();
      toast.error(
        err instanceof Error ? err.message : "Failed to update visibility"
      );
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal open={open} onOpenChange={(isOpen) => !isOpen && onClose()}>
      <Modal.Content width="md">
        <Modal.Header
          icon={SvgShare}
          title={`Share "${skill.name}"`}
          description="Visibility controls who sees this skill in their Craft session."
          onClose={onClose}
        />
        <Modal.Body>
          <Section gap={1} alignItems="stretch">
            <SkillSharePicker
              isPublic={isPublic}
              onIsPublicChange={setIsPublic}
              groupIds={groupIds}
              onGroupIdsChange={setGroupIds}
            />
          </Section>
        </Modal.Body>
        <Modal.Footer>
          <Button prominence="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button disabled={saving} onClick={handleSave}>
            {saving ? "Saving…" : "Save"}
          </Button>
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}
