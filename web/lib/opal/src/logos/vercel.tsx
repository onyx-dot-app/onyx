import type { IconProps } from "@opal/types";

function SvgVercel({ size, ...props }: IconProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      {...props}
    >
      <path d="M12 1.5L23.2 21H0.8L12 1.5Z" fill="currentColor" />
    </svg>
  );
}

export default SvgVercel;
