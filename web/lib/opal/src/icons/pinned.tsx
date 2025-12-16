import type { IconProps } from "@/types/icons";

const SvgPinned = ({ size, ...props }: IconProps) => (
  <svg
    width={size}
    height={size}
    xmlns="http://www.w3.org/2000/svg"
    viewBox="0 0 16 16"
    fill="none"
    stroke="currentColor"
    {...props}
  >
    <path
      d="M8 8.85714V14.14286M8 8.85714L13.14286 8.85714C14.03377 8.85714 14.47993 7.78 13.84997 7.15003L12.90022 6.20028C12.33761 5.63767 12.02155 4.87461 12.02155 4.07896V2.78571C12.02155 2.23342 11.57384 1.78571 11.02155 1.78571L4.97845 1.78571C4.42616 1.78571 3.97845 2.23342 3.97845 2.78571L3.97845 4.07896C3.97845 4.87461 3.66238 5.63767 3.09977 6.20028L2.15002 7.15003C1.52006 7.78 1.96622 8.85714 2.85713 8.85714H8Z"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

export default SvgPinned;
