import type { IconProps } from "@opal/types";
const SvgCreditCard = ({ size, ...props }: IconProps) => (
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
      d="M14.6667 6V4.00008C14.6667 3.26675 14.0667 2.66675 13.3333 2.66675H2.66668C1.93334 2.66675 1.33334 3.26675 1.33334 4.00008V6M14.6667 6V12.0001C14.6667 12.7334 14.0667 13.3334 13.3333 13.3334H2.66668C1.93334 13.3334 1.33334 12.7334 1.33334 12.0001V6M14.6667 6H1.33334"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgCreditCard;
