"use client";

import { useRouter } from "next/navigation";
import { useSessionWatcher } from "@/lib/auth/hooks";
import { getExtensionContext } from "@/lib/extension/utils";
import Modal from "@/refresh-components/Modal";
import { Button, Text } from "@opal/components";
import { SvgLogOut } from "@opal/icons";

interface AuthenticationShellProps {
  children: React.ReactNode;
}

export function AuthenticationShell({ children }: AuthenticationShellProps) {
  const router = useRouter();
  const sessionEnded = useSessionWatcher();

  function handleLogin() {
    const { isExtension } = getExtensionContext();
    if (isExtension) {
      window.open(
        window.location.origin + "/auth/login",
        "_blank",
        "noopener,noreferrer"
      );
    } else {
      router.push("/auth/login");
    }
  }

  return (
    <>
      <div
        className={sessionEnded ? "pointer-events-none select-none" : undefined}
      >
        {children}
      </div>
      {sessionEnded && (
        <Modal open>
          <Modal.Content width="sm" height="sm">
            <Modal.Header icon={SvgLogOut} title="You Have Been Logged Out" />
            <Modal.Body>
              <Text font="main-ui-body" color="text-03">
                Your session has expired. Please log in again to continue.
              </Text>
            </Modal.Body>
            <Modal.Footer>
              <Button onClick={handleLogin}>Log In</Button>
            </Modal.Footer>
          </Modal.Content>
        </Modal>
      )}
    </>
  );
}
