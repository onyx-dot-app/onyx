import type { IconProps } from "@opal/types";
const SvgArrowWallRight = ({ size, ...props }: IconProps) => (
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
      d="M9.44281 5.16673L11.8047 7.52866C11.9349 7.65883 12 7.82944 12 8.00006M9.44281 10.8334L11.8047 8.47146C11.9349 8.34129 12 8.17068 12 8.00006M2 8.00006H12M15 3.16675V12.8334"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgArrowWallRight;
