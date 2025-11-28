import { ReactNode } from "react";

export interface InlineExternalLinkProps {
  href: string;
  children: ReactNode;
  className?: string;
}

export default function InlineExternalLink({
  href,
  children,
  className,
}: InlineExternalLinkProps) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className={className ?? "underline"}
    >
      {children}
    </a>
  );
}
