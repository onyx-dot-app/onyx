"use client";

import { Button, Divider } from "@tremor/react";
import { Modal } from "../Modal";
import { useState } from "react";

export function UserDisclaimerModal(props: any) {
  const { disclaimerTitle, disclaimerText } = props;
  const [isHidden, setIsHidden] = useState(false);

  if (disclaimerText == "") {
    return null;
  }
  if (isHidden) {
    window.justLoggedIn = false;
    return null;
  }
  if (!window.justLoggedIn) {
    return null;
  }
  return (
    <Modal
      className="max-w-4xl"
      title={disclaimerTitle}
      onOutsideClick={() => setIsHidden(true)}
    >
      <div className="text-base">
        <div>
          <p dangerouslySetInnerHTML={{ __html: disclaimerText }} />
        </div>
        <Divider />
        <Button className="mx-auto w-full" onClick={() => setIsHidden(true)}>
          OK
        </Button>
      </div>
    </Modal>
  );
}
