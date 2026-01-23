"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Modal, { BasicModalFooter } from "@/refresh-components/Modal";
import Button from "@/refresh-components/buttons/Button";
import Text from "@/refresh-components/texts/Text";
import { SvgLock, SvgArrowRight, SvgBubbleText } from "@opal/icons";
import { logout } from "@/lib/user";

interface NotAllowedModalProps {
  open: boolean;
}

export default function NotAllowedModal({ open }: NotAllowedModalProps) {
  const router = useRouter();
  const [isLoading, setIsLoading] = useState(false);

  const handleReturnToChat = () => {
    router.push("/chat");
  };

  const handleCreateNewAccount = async () => {
    setIsLoading(true);
    try {
      await logout();
      router.push("/auth/signup");
    } finally {
      setIsLoading(false);
    }
  };

  if (!open) return null;

  return (
    <Modal open>
      <Modal.Content width="sm" height="fit">
        <Modal.Header
          icon={SvgLock}
          title="Build Mode Access Restricted"
          description="Build Mode is only available to admins and curators. Please contact your administrator to request access."
        />

        <Modal.Footer>
          <BasicModalFooter
            cancel={
              <Button
                onClick={handleReturnToChat}
                secondary
                leftIcon={SvgBubbleText}
              >
                Return to Chat
              </Button>
            }
            submit={
              <Button
                onClick={handleCreateNewAccount}
                disabled={isLoading}
                rightIcon={SvgArrowRight}
              >
                {isLoading ? "Signing out..." : "Create a new account"}
              </Button>
            }
          />
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}
