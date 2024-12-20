"use client";

import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";

import { Modal } from "../Modal";
import { useState, useEffect } from "react";
import Cookies from "js-cookie";

export function UserDisclaimerModal(props: any) {
  const { disclaimerTitle, disclaimerText } = props;
  const [show, setShow] = useState(false);
  const justLoggedIn = Cookies.get("JUST_LOGGED_IN");

  if (justLoggedIn){
    setShow(true);
    Cookies.remove("JUST_LOGGED_IN");
  }

  // useEffect(() => {
  //   if (window.justLoggedIn) {
  //     setShow(true)
  //     window.justLoggedIn = false;
  //   }
  // }, []);
  return (show && disclaimerText != "") ? (
    <Modal
      className="max-w-4xl"
      title={disclaimerTitle}
      onOutsideClick={() => setShow(false)}
    >
      <div className="text-base">
        <div>
          <p dangerouslySetInnerHTML={{ __html: disclaimerText }} />
        </div>
        <Separator />
        <Button className="mx-auto w-full" onClick={() => setShow(false)}>
          OK
        </Button>
      </div>
    </Modal>
  ) : null;
}
