import type { IconProps } from "@opal/types";
const SvgFileMinus = ({ size, ...props }: IconProps) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 12 12"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    stroke="currentColor"
    {...props}
  >
    <path
      d="M10 4L7 1H3C2.45533 1 2 1.45533 2 2V10C2 10.5447 2.45533 11 3 11H9C9.54467 11 10 10.5447 10 10V4ZM7 1L7 4L10 4M4.5 7.5H7.5"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgFileMinus;
