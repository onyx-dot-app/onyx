import type { IconProps } from "@opal/types";

const SvgKeyboard = ({ size, ...props }: IconProps) => (
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
      d="M2.66668 3.33337H13.3333C14.0697 3.33337 14.6667 3.93033 14.6667 4.66671V11.3334C14.6667 12.0698 14.0697 12.6667 13.3333 12.6667H2.66668C1.9303 12.6667 1.33334 12.0698 1.33334 11.3334V4.66671C1.33334 3.93033 1.9303 3.33337 2.66668 3.33337Z"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
    <path
      d="M4 6H4.00667M6.66667 6H6.67334M9.33334 6H9.34001M12 6H12.0067M4 8H4.00667M6.66667 8H6.67334M9.33334 8H9.34001M12 8H12.0067M5.33334 10.3334H10.6667"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgKeyboard;
