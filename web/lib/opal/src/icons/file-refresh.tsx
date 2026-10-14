import type { IconProps } from "@opal/types";
const SvgFileRefresh = ({ size, ...props }: IconProps) => (
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
      d="M10 4V10C10 10.5447 9.54467 11 9 11H3C2.45533 11 2 10.5447 2 10V2C2 1.45533 2.45533 1 3 1H7L8.25002 2.25002M6.9375 5.31103H8.25V3.99753M8.25 5.31103L7.59155 4.65378C7.18434 4.24627 6.6216 3.99753 5.99999 3.99753C5.02033 3.99753 4.1869 4.62363 3.87802 5.49753M8.12189 6.99773C7.81296 7.87152 6.97958 8.49753 5.99999 8.49753C5.37789 8.49753 4.81475 8.25315 4.40746 7.84507L3.75 7.18505M5.0625 7.18505H3.75V8.49753"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgFileRefresh;
