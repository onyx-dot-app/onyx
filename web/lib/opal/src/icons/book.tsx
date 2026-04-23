import type { IconProps } from "@opal/types";
const SvgBook = ({ size, ...props }: IconProps) => (
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
      d="M2.66666 13V2.99998C2.66666 2.0922 3.42555 1.33331 4.33332 1.33331H13.3333V14.6666H4.33332C3.42554 14.6666 2.66666 13.9078 2.66666 13ZM2.66666 13C2.66666 12.0922 3.42555 11.3333 4.33332 11.3333H13.3333"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgBook;
