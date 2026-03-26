"use client";

import Modal from "@/refresh-components/Modal";
import { Button, Text } from "@opal/components";
import { useUser } from "@/providers/UserProvider";
import { SvgUser } from "@opal/icons";

export default function NoAgentModal() {
  const { isAdmin } = useUser();

  return (
    <Modal open>
      <Modal.Content width="sm" height="sm">
        <Modal.Header icon={SvgUser} title="No Agent Available" />
        <Modal.Body>
          <Text as="p" color="text-05">
            You currently have no agent configured. To use this feature, you
            need to take action.
          </Text>
          {isAdmin ? (
            <>
              <Text as="p" color="text-05">
                As an administrator, you can create a new agent by visiting the
                admin panel.
              </Text>
              <Button width="full" href="/admin/agents">
                Go to Admin Panel
              </Button>
            </>
          ) : (
            <Text as="p" color="text-05">
              Please contact your administrator to configure an agent for you.
            </Text>
          )}
        </Modal.Body>
      </Modal.Content>
    </Modal>
  );
}
