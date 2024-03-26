"use client";

import { Button, Divider } from "@tremor/react";
import { Modal } from "../Modal";
import Link from "next/link";
import { FiMessageSquare, FiShare2 } from "react-icons/fi";
import { useState, useEffect } from "react";

export function UserDisclaimerModal() {
  const [isHidden, setIsHidden] = useState(false);

  if (isHidden) {
    window.justLoggedIn = false;
    return null;
  }
  if (!window.justLoggedIn){
    return null;
  }

  return (
    
    <Modal
      className="max-w-4xl"
      title="Disclaimer"
      onOutsideClick={() => setIsHidden(true)}
    >
      <div className="text-base">
        <div>
          <p>
            You are connected
          </p>
          <p>
            Be careful
          </p>
        </div>
        <Divider />
        <Button
          className="mx-auto w-full"
          onClick={() => setIsHidden(true)}
          >
          OK
        </Button>
      </div>
    </Modal>
  )
}
