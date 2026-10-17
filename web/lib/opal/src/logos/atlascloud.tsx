import type { IconProps } from "@opal/types";

function SvgAtlascloud({ size, ...props }: IconProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      {...props}
    >
      <path d="M2 19L8 7L12 14L15 9L22 19H2Z" fill="currentColor" />
    </svg>
  );
}

export default SvgAtlascloud;
