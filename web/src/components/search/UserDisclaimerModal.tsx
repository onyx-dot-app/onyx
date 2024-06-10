"use client";

import { Button, Divider } from "@tremor/react";
import { Modal } from "../Modal";
import { useState, useEffect } from "react";

export function UserDisclaimerModal(props: any) {
  const { disclaimerTitle, disclaimerText } = props;
  const [show, setShow] = useState(false);

  if (disclaimerText == "") {
    return null;
  }

  useEffect(() => {
    if (window.justLoggedIn) {
      setShow(true)
      window.justLoggedIn = false;
    }
  }, []);

  return show ? (
    <Modal
      className="max-w-4xl"
      title={disclaimerTitle}
      onOutsideClick={() => setShow(false)}
    >
      <div className="text-base">
        <div>
          <p dangerouslySetInnerHTML={{ __html: disclaimerText }} />
        </div>
        <Divider />
        <Button className="mx-auto w-full" onClick={() => setShow(false)}>
          OK
        </Button>
      </div>
    </Modal>
  ) : null;
}
