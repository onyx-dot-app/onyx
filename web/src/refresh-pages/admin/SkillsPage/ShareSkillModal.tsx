"use client";

import { useEffect, useState } from "react";
import { Button } from "@opal/components";
import { SvgGlobe, SvgShare } from "@opal/icons";
import Modal from "@/refresh-components/Modal";
import Text from "@/refresh-components/texts/Text";
import { Section } from "@/layouts/general-layouts";
import VisibilityPicker from "@/refresh-pages/admin/SkillsPage/VisibilityPicker";
import type {
  CustomSkill,
  SkillVisibility,
} from "@/refresh-pages/admin/SkillsPage/interfaces";

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface ShareSkillModalProps {
  skill: CustomSkill | null;
  open: boolean;
  onClose: () => void;
  /** True iff the current user is an admin for this skill (admin or author). */
  canSetOrgWide: boolean;
  onSave: (visibility: SkillVisibility) => void;
  onRequestOrgWide?: () => void;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function ShareSkillModal({
  skill,
  open,
  onClose,
  canSetOrgWide,
  onSave,
  onRequestOrgWide,
}: ShareSkillModalProps) {
  const [visibility, setVisibility] = useState<SkillVisibility>(
    skill?.visibility ?? "private"
  );

  useEffect(() => {
    if (skill) setVisibility(skill.visibility);
  }, [skill]);

  if (!skill) return null;

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
            <VisibilityPicker
              visibility={visibility}
              onChange={setVisibility}
              canSetOrgWide={canSetOrgWide}
            />

            {/*
              In a real implementation, "Specific users" / "Groups" /
              "Users + groups" would render multi-select pickers here.
              For the wireframe we keep it simple.
            */}
            {(visibility === "users" ||
              visibility === "groups" ||
              visibility === "users_and_groups") && (
              <div className="rounded-md border border-dashed border-border-02 p-4 bg-background-tint-01">
                <Text as="p" mainUiBody text03>
                  Picker for individual users / groups would render here.
                  Wireframe-only — no live data binding yet.
                </Text>
              </div>
            )}
          </Section>
        </Modal.Body>
        <Modal.Footer>
          {!canSetOrgWide && onRequestOrgWide && (
            <Button
              prominence="secondary"
              icon={SvgGlobe}
              onClick={() => {
                onRequestOrgWide();
                onClose();
              }}
            >
              {skill.promotion_requested
                ? "Org-wide requested"
                : "Request org-wide"}
            </Button>
          )}
          <Button prominence="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button
            onClick={() => {
              onSave(visibility);
              onClose();
            }}
          >
            Save
          </Button>
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}
