import type { IconProps } from "@opal/types";
const SvgCornerRightUpDot = ({ size, ...props }: IconProps) => (
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
      d="M12.9997 7.94975V3H8.05M12.9997 3L7.5 8.5M4.50001 13C3.67158 13 3 12.3284 3 11.5C3 10.6716 3.67158 10 4.50001 10C5.32845 10 6 10.6716 6 11.5C6 12.3284 5.32845 13 4.50001 13Z"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgCornerRightUpDot;
