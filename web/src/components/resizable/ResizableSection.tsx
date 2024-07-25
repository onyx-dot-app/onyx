"use client";

import React, { useEffect, useState } from "react";
import Cookies from "js-cookie";
import { DOCUMENT_SIDEBAR_WIDTH_COOKIE_NAME } from "./constants";

function applyMinAndMax(
  width: number,
  minWidth: number | undefined,
  maxWidth: number | undefined
) {
  let newWidth = width;
  if (minWidth) {
    newWidth = Math.max(width, minWidth); // Ensure the width doesn't go below a minimum value
  }
  if (maxWidth) {
    newWidth = Math.min(newWidth, maxWidth); // Ensure the width doesn't exceed a maximum value
  }
  return newWidth;
}

export function ResizableSection({
  updateSidebarWidth,
  children,
  intialWidth,
  minWidth,
  maxWidth,
}: {
  updateSidebarWidth?: (newWidth: number) => void;
  children: JSX.Element;
  intialWidth: number;
  minWidth: number;
  maxWidth?: number;
}) {
  const [width, setWidth] = useState<number>(intialWidth);
  const [isResizing, setIsResizing] = useState<boolean>(false);

  useEffect(() => {
    const newWidth = applyMinAndMax(width, minWidth, maxWidth);
    setWidth(newWidth);
    Cookies.set(DOCUMENT_SIDEBAR_WIDTH_COOKIE_NAME, newWidth.toString(), {
      path: "/",
    });
  }, [minWidth, maxWidth]);

  const startResizing = (mouseDownEvent: React.MouseEvent<HTMLDivElement>) => {
    setIsResizing(true);

    // Disable text selection
    document.body.style.userSelect = "none";
    document.body.style.cursor = "col-resize";

    // Record the initial position of the mouse
    const startX = mouseDownEvent.clientX;

    const handleMouseMove = (mouseMoveEvent: MouseEvent) => {
      // Calculate the change in position
      const delta = mouseMoveEvent.clientX - startX;
      let newWidth = applyMinAndMax(width + delta, minWidth, maxWidth);
      setWidth(newWidth);
      if (updateSidebarWidth) {
        updateSidebarWidth(newWidth);
      }
      Cookies.set(DOCUMENT_SIDEBAR_WIDTH_COOKIE_NAME, newWidth.toString(), {
        path: "/",
      });
    };
    const stopResizing = () => {
      // Re-enable text selection
      document.body.style.userSelect = "";
      document.body.style.cursor = "";

      // Remove the event listeners
      window.removeEventListener("mousemove", handleMouseMove);
      window.removeEventListener("mouseup", stopResizing);

      setIsResizing(false);
    };

    window.addEventListener("mousemove", handleMouseMove);
    window.addEventListener("mouseup", stopResizing);
  };

  return (
    <div className="flex h-full">
      <div
        style={{ width: `${width}px` }}
        className={`resize-section h-full flex`}
      >
        {children}
      </div>
      <div
        className={`
          -mr-1 
          pr-1 
          z-30
          h-full 
      `}
      >
        <div
          onMouseDown={startResizing}
          className={`
          cursor-col-resize 
          border-r 
          border-border 
          h-full
          w-full
          transition-all duration-300 ease-in hover:border-border-strong hover:border-r-2
          ${
            isResizing
              ? "transition-all duration-300 ease-in border-border-strong border-r-2"
              : ""
          }
          `}
        ></div>
      </div>
    </div>
  );
}

export default ResizableSection;
