import type { IconProps } from "@opal/types";
const SvgBookmark = ({ size, ...props }: IconProps) => (
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
      d="M12.6667 14L7.99999 10.6667L3.33333 14V3.33333C3.33333 2.97971 3.4738 2.64057 3.72385 2.39052C3.9739 2.14048 4.31304 2 4.66666 2H11.3333C11.6869 2 12.0261 2.14048 12.2761 2.39052C12.5262 2.64057 12.6667 2.97971 12.6667 3.33333V14Z"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgBookmark;
