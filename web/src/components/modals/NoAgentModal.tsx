"use client";

import Modal from "@/refresh-components/Modal";
import Button from "@/refresh-components/buttons/Button";
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
                admin panel.
              </Text>
<<<<<<< HEAD:web/src/components/modals/NoAgentModal.tsx
              <Button className="w-full" href="/admin/agents">
=======
              {/* TODO(opal-migration): migrate to opal Button once className/iconClassName/onHover is removed */}
              <Button className="w-full" href="/admin/assistants">
>>>>>>> 99f4dcc5d (chore(fe): opal button migration):web/src/components/modals/NoAssistantModal.tsx
                Go to Admin Panel
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
