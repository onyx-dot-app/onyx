import type { IconProps } from "@opal/types";

function SvgActivaLogo({
  size = 16,
  width,
  height,
  className,
  title,
  ...props
}: IconProps) {
  const resolvedWidth = width ?? size;
  const resolvedHeight = height ?? size;

  return (
    <svg
      width={resolvedWidth}
      height={resolvedHeight}
      viewBox="0 0 400 400"
      xmlns="http://www.w3.org/2000/svg"
      className={className}
      role="img"
      aria-hidden={title ? undefined : true}
      {...props}
    >
      {title ? <title>{title}</title> : null}
      <image
        href="/logo.png"
        width="400"
        height="400"
        preserveAspectRatio="xMidYMid meet"
        className="dark:hidden"
      />
      <image
        href="/logo-dark.png"
        width="400"
        height="400"
        preserveAspectRatio="xMidYMid meet"
        className="hidden dark:block"
      />
    </svg>
  );
}

export default SvgActivaLogo;
