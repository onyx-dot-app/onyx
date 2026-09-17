import type { IconProps } from "@opal/types";
const SvgFolderPartialOpen = ({ size, ...props }: IconProps) => (
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
      d="M14.5 6.73782V6C14.5 5.17157 13.8284 4.5 13 4.5H9.1213C8.7235 4.5 8.342 4.34196 8.0607 4.06066L6.93934 2.93934C6.65804 2.65804 6.2765 2.5 5.87868 2.5H3C2.17157 2.5 1.5 3.17157 1.5 4V6.7378"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
    <path
      d="M14.5963 12.1032C14.5421 12.8897 13.8883 13.5 13.0999 13.5H2.90011C2.11174 13.5 1.45791 12.8897 1.40366 12.1032L1.11056 7.8532C1.05077 6.98621 1.73795 6.25 2.607 6.25H13.393C14.262 6.25 14.9492 6.9862 14.8894 7.8532L14.5963 12.1032Z"
      strokeWidth={1.5}
      strokeLinecap="round"
    />
  </svg>
);
export default SvgFolderPartialOpen;
