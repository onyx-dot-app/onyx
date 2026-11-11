import type { IconProps } from "@opal/types";
const SvgFileRefresh = ({ size, ...props }: IconProps) => (
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
      d="M13.33333 5.33333V13.33333C13.33333 14.0596 12.72623 14.66667 12 14.66667H4C3.27377 14.66667 2.66667 14.0596 2.66667 13.33333V2.66667C2.66667 1.94044 3.27377 1.33333 4 1.33333H9.33333L11.00003 3.00003M9.25 7.08137H11V5.33004M11 7.08137L10.12207 6.20504C9.57912 5.66169 8.8288 5.33004 7.99999 5.33004C6.69377 5.33004 5.58253 6.16484 5.17069 7.33004M10.82919 9.33031C10.41728 10.49536 9.30611 11.33004 7.99999 11.33004C7.17052 11.33004 6.41967 11.0042 5.87661 10.46009L5 9.58007M6.75 9.58007H5V11.33004"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgFileRefresh;
