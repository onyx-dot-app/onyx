"use client";

import React, { ReactNode, useEffect, useState } from "react";
import { useRouter } from "next/navigation";

export default function FunctionalWrapper({
  sidebarInitiallyVisible,
  content,
}: {
  content: (
    sidebarVisible: boolean,
    toggle: (toggled?: boolean) => void
  ) => ReactNode;
  sidebarInitiallyVisible: boolean;
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

  const [sidebarVisible, setSidebarVisible] = useState(sidebarInitiallyVisible);

  const toggle = (value?: boolean) => {
    setSidebarVisible((sidebarVisible) =>
      value !== undefined ? value : !sidebarVisible
    );
  };

  return (
    <>
      {" "}
      <div className="overscroll-y-contain overflow-y-scroll overscroll-contain left-0 top-0 w-full h-svh">
        {content(sidebarVisible, toggle)}
      </div>
    </>
  );
}
