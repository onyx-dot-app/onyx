"use client";

import Modal from "@/refresh-components/Modal";
import { Button, Text } from "@opal/components";
import { SvgLogOut } from "@opal/icons";

interface LoggedOutModalProps {
  onLogin: () => void;
}

export default function LoggedOutModal({ onLogin }: LoggedOutModalProps) {
  return (
    <Modal open>
      <Modal.Content width="sm" height="sm">
        <Modal.Header icon={SvgLogOut} title="You Have Been Logged Out" />
        <Modal.Body>
          <Text font="main-ui-body" color="text-03">
            Your session has expired. Please log in again to continue.
          </Text>
        </Modal.Body>
        <Modal.Footer>
          <Button onClick={onLogin}>Log In</Button>
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}
