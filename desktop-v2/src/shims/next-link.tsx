// Opal's navigation layer imports next/link; local desktop windows have no router.
import { forwardRef, type AnchorHTMLAttributes } from "react";

type LinkProps = Omit<AnchorHTMLAttributes<HTMLAnchorElement>, "href"> & {
  href: string | { pathname?: string };
  prefetch?: boolean;
  replace?: boolean;
  scroll?: boolean;
};

const Link = forwardRef<HTMLAnchorElement, LinkProps>(function Link(
  { href, prefetch: _prefetch, replace: _replace, scroll: _scroll, ...rest },
  ref
) {
  const target = typeof href === "string" ? href : (href.pathname ?? "#");
  return <a ref={ref} href={target} {...rest} />;
});

export default Link;
