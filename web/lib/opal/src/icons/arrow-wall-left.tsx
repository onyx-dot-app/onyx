import type { IconProps } from "@opal/types";
const SvgArrowWallLeft = ({ size, ...props }: IconProps) => (
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
      d="M6.55719 5.16673L4.19527 7.52866C4.06509 7.65883 4 7.82944 4 8.00006M6.55719 10.8334L4.19526 8.47146C4.06509 8.34129 4 8.17068 4 8.00006M14 8.00006H4M1 3.16675V12.8334"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgArrowWallLeft;
