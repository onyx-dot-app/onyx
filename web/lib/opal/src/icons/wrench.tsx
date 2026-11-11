import type { IconProps } from "@opal/types";

export default function SvgWrench({ size, ...props }: IconProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 16 16"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      stroke="currentColor"
      {...props}
    >
      <path
        d="M9.6 2.1a3.7 3.7 0 0 0-4.3 5.1l-3.1 3.1a1.9 1.9 0 0 0 2.7 2.7L8 9.9a3.7 3.7 0 0 0 5.1-4.3l-2.4 2.1-2.9-2.9L9.6 2.1Z"
        strokeWidth={1.5}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
