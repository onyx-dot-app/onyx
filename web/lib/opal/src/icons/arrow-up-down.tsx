import type { IconProps } from "@opal/types";

const SvgArrowUpDown = ({ size, ...props }: IconProps) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 13 12"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    stroke="currentColor"
    {...props}
  >
    <path
      d="M11.75 2.97381L9.72145 0.945267C9.59128 0.81509 9.42066 0.750002 9.25005 0.750001M6.74999 2.97392L8.77865 0.94526C8.90881 0.815087 9.07943 0.75 9.25005 0.750001M9.25005 10.75V0.750001M5.74996 8.52613L3.72141 10.5547C3.59124 10.6849 3.42062 10.75 3.25001 10.75M0.75 8.52613L2.77861 10.5547C2.90877 10.6849 3.07939 10.75 3.25001 10.75M3.25001 0.75L3.25001 10.75"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgArrowUpDown;
