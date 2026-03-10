import React from "react";

interface LinkProps {
  href: string;
  children: React.ReactNode;
  [key: string]: unknown;
}

function Link({
  href,
  children,
  prefetch: _prefetch,
  scroll: _scroll,
  shallow: _shallow,
  replace: _replace,
  passHref: _passHref,
  locale: _locale,
  legacyBehavior: _legacyBehavior,
  ...props
}: LinkProps) {
  return (
    <a href={href} {...props}>
      {children}
    </a>
  );
}

export default Link;
