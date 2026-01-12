"use client";

import { useState } from "react";
import {
  MinimalPersonaSnapshot,
  Persona,
} from "@/app/admin/assistants/interfaces";
import Modal, { BasicModalFooter } from "@/refresh-components/Modal";
import Button from "@/refresh-components/buttons/Button";
import { SvgLink, SvgOrganization, SvgShare, SvgUsers } from "@opal/icons";
import { addUsersToAssistantSharedList } from "@/lib/assistants/shareAssistant";
import Tabs from "@/refresh-components/Tabs";
import { Card } from "@/refresh-components/cards";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import * as InputLayouts from "@/layouts/input-layouts";
import Switch from "@/refresh-components/inputs/Switch";
import Separator from "@/refresh-components/Separator";

export interface AgentShareModalProps {
  agent?: MinimalPersonaSnapshot | Persona;
}

export default function AgentShareModal({ agent }: AgentShareModalProps) {
  const [selectedUserIds, setSelectedUserIds] = useState<string[]>([]);
  const [isSharing, setIsSharing] = useState(false);

  async function handleShare() {
    if (selectedUserIds.length === 0) return;
    setIsSharing(true);

    try {
      // Type assertion needed because addUsersToAssistantSharedList expects full Persona
      // but works fine with MinimalPersonaSnapshot as it only needs id and users array
      const error = await addUsersToAssistantSharedList(
        agent as Persona,
        selectedUserIds
      );
      if (error) return;

      setSelectedUserIds([]);
    } finally {
      setIsSharing(false);
    }
  }

  function handleClose() {
    setSelectedUserIds([]);
  }

  return (
    <Modal.Content small>
      <Modal.Header icon={SvgShare} title="Share Agent" onClose={handleClose} />

      <Modal.Body padding={0.5}>
        <Card borderless padding={0.5}>
          <Tabs defaultValue="Users & Groups">
            <Tabs.List>
              <Tabs.Trigger icon={SvgUsers} value="Users & Groups">
                Users &amp; Groups
              </Tabs.Trigger>
              <Tabs.Trigger icon={SvgOrganization} value="Your Organization">
                Your Organization
              </Tabs.Trigger>
            </Tabs.List>

            <Tabs.Content value="Users & Groups">
              <InputTypeIn placeholder="Add uses, groups, and accounts" />
            </Tabs.Content>
            <Tabs.Content value="Your Organization" padding={0.5}>
              <InputLayouts.Horizontal
                label="Publish This Agent"
                description="Make this agent available to everyone in your organization."
              >
                <Switch />
              </InputLayouts.Horizontal>
              <Separator noPadding />
              <InputLayouts.Horizontal
                label="Feature This Agent"
                description="Show this agent in the featured section in the explore list for everyone in your organization. This will also pin the agent for any new users."
              >
                <Switch />
              </InputLayouts.Horizontal>
            </Tabs.Content>
          </Tabs>
        </Card>
      </Modal.Body>

      <Modal.Footer>
        <BasicModalFooter
          left={
            <Button secondary leftIcon={SvgLink}>
              Copy Link
            </Button>
          }
          cancel={
            <Button secondary onClick={handleClose} disabled={isSharing}>
              Done
            </Button>
          }
          submit={
            <Button
              onClick={handleShare}
              disabled={selectedUserIds.length === 0 || isSharing}
            >
              Share
            </Button>
          }
        />
      </Modal.Footer>
    </Modal.Content>
  );
}
