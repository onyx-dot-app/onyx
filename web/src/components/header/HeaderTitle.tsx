"use client";

import React from "react";

export function HeaderTitle({ children }: { children: JSX.Element | string }) {
  const isString = typeof children === "string";
  const textSize = isString && children.length > 10 ? "text-xl" : "text-2xl";

  return (
    <h1
      className={`${textSize} break-words line-clamp-2 ellipsis text-strong leading-none font-bold`}
    >
      {children}
    </h1>
  );
}
