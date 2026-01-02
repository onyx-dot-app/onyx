import type { IconProps } from "@opal/types";

const SvgRevert = ({ size, ...props }: IconProps) => (
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
      d="M1.33333 2V6M1.33333 6H5.33333M1.33333 6L4.00432 3.33333C5.05887 2.27806 6.50634 1.66667 8.06318 1.66667C11.2745 1.66667 13.8799 4.27203 13.8799 7.48333C13.8799 10.6946 11.2745 13.3 8.06318 13.3C5.52018 13.3 3.35026 11.6635 2.54132 9.38632"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgRevert;
