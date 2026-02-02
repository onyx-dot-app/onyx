import type { IconProps } from "@opal/types";

const SvgBranch = ({ size, ...props }: IconProps) => (
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
      d="M4.75001 5C5.71651 5 6.50001 4.2165 6.50001 3.25C6.50001 2.2835 5.7165 1.5 4.75 1.5C3.78351 1.5 3.00001 2.2835 3.00001 3.25C3.00001 4.2165 3.78351 5 4.75001 5ZM4.75001 5L4.75001 6.24999M4.75 11C3.7835 11 3 11.7835 3 12.75C3 13.7165 3.7835 14.5 4.75 14.5C5.7165 14.5 6.5 13.7165 6.5 12.75C6.5 11.7835 5.71649 11 4.75 11ZM4.75 11L4.75001 6.24999M10.5 8.74997C10.5 9.71646 11.2835 10.5 12.25 10.5C13.2165 10.5 14 9.71646 14 8.74997C14 7.78347 13.2165 7 12.25 7C11.2835 7 10.5 7.78347 10.5 8.74997ZM10.5 8.74997L7.25001 8.74999C5.8693 8.74999 4.75001 7.6307 4.75001 6.24999"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgBranch;
