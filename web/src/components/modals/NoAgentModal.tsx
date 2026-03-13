"use client";

import Modal from "@/refresh-components/Modal";
import { Button } from "@opal/components";
import Text from "@/refresh-components/texts/Text";
import { useUser } from "@/providers/UserProvider";
import { SvgUser } from "@opal/icons";

export default function NoAgentModal() {
  const { isAdmin } = useUser();

  return (
    <Modal open>
      <Modal.Content width="sm" height="sm">
        <Modal.Header icon={SvgUser} title="No Agent Available" />
        <Modal.Body>
          <Text as="p">
            You currently have no agent configured. To use this feature, you
            need to take action.
          </Text>
          {isAdmin ? (
            <>
              <Text as="p">
                As an administrator, you can create a new agent by visiting the
                admin settings.
              </Text>
              <Button width="full" href="/admin/agents">
                Go to Admin Settings
              </Button>
            </>
          ) : (
            <Text as="p">
              Please contact your administrator to configure an agent for you.
            </Text>
          )}
        </Modal.Body>
      </Modal.Content>
    </Modal>
  );
}
