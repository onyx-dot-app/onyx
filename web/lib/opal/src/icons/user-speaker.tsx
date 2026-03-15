import type { IconProps } from "@opal/types";
const SvgUserSpeaker = ({ size, ...props }: IconProps) => (
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
      d="M1 14C1 13.6667 1 13.3333 1 13C1 11.3431 2.34316 10 4.00002 10H7.99998C9.65684 10 11 11.3431 11 13C11 13.3333 11 13.6667 11 14H14.5V10L12.7071 8.20711M12 7.5L12.7071 8.20711M12.7071 8.20711C13.0976 7.81658 13.0976 7.18342 12.7071 6.79289C12.3166 6.40237 11.6834 6.40237 11.2929 6.79289C10.9024 7.18342 10.9024 7.81658 11.2929 8.20711C11.6834 8.59763 12.3166 8.59763 12.7071 8.20711ZM8.75 4.75C8.75 6.26878 7.51878 7.5 6 7.5C4.48122 7.5 3.25 6.26878 3.25 4.75C3.25 3.23122 4.48122 2 6 2C7.51878 2 8.75 3.23122 8.75 4.75Z"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgUserSpeaker;
