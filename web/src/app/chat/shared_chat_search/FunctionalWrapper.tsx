"use client";

import React, { ReactNode, useEffect, useState } from "react";
import { useRouter } from "next/navigation";

export default function FunctionalWrapper({
  initiallyToggled,
  content,
}: {
  content: (
    toggledSidebar: boolean,
    toggle: (toggled?: boolean) => void
  ) => ReactNode;
  initiallyToggled: boolean;
}) {
  const router = useRouter();

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.metaKey || event.ctrlKey) {
        const newPage = event.shiftKey;
        switch (event.key.toLowerCase()) {
          case "d":
            event.preventDefault();
            if (newPage) {
              window.open("/chat", "_blank");
            } else {
              router.push("/chat");
            }
            break;
          case "s":
            event.preventDefault();
            if (newPage) {
              window.open("/search", "_blank");
            } else {
              router.push("/search");
            }
            break;
        }
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [router]);

  const [toggledSidebar, setToggledSidebar] = useState(initiallyToggled);

  const toggle = (value?: boolean) => {
    setToggledSidebar((toggledSidebar) =>
      value !== undefined ? value : !toggledSidebar
    );
  };

  return (
    <>
      {" "}
      <div className="overscroll-y-contain overflow-y-scroll overscroll-contain left-0 top-0 w-full h-svh">
        {content(toggledSidebar, toggle)}
      </div>
    </>
  );
}
