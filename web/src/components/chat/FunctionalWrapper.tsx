"use client";

import React, { ReactNode, useState } from "react";

export default function FunctionalWrapper({
  initiallyVisible,
  content,
}: {
  content: (
    sidebarVisible: boolean,
    toggle: (visible?: boolean) => void
  ) => ReactNode;
  initiallyVisible?: boolean;
}) {
  const [sidebarVisible, setSidebarVisible] = useState(
    initiallyVisible || false
  );

  const toggle = (value?: boolean) => {
    setSidebarVisible((sidebarVisible) =>
      value !== undefined ? value : !sidebarVisible
    );
  };

  return (
    <>
      <div className="overscroll-y-contain overflow-y-scroll overscroll-contain left-0 top-0 w-full h-svh">
        {content(sidebarVisible, toggle)}
      </div>
    </>
  );
}
