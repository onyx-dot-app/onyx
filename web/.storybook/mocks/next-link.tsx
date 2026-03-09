import React from "react";

interface LinkProps {
  href: string;
  children: React.ReactNode;
  [key: string]: unknown;
}

function Link({ href, children, ...props }: LinkProps) {
  return (
    <a href={href} {...props}>
      {children}
    </a>
  );
}

export default Link;
