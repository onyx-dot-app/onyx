interface Props {
  children: JSX.Element | string;
  onClick?: React.MouseEventHandler<HTMLButtonElement>;
  type?: "button" | "submit" | "reset";
  disabled?: boolean;
  className?: string;
}

export const Button = ({
  children,
  onClick,
  type = "submit",
  disabled = false,
  className = "",
}: Props) => {
  return (
    <button
      className={
        "group relative " +
        "py-1 px-2 border border-transparent text-sm " +
        "font-medium rounded-md text-white " +
        "focus:outline-none focus:ring-2 " +
        "focus:ring-offset-2 focus:ring-red-500 mx-auto " +
        (disabled ? "bg-background-700 " : "bg-red-800 hover:bg-red-900 ") +
        className
      }
      onClick={onClick}
      type={type}
      disabled={disabled}
    >
      {children}
    </button>
  );
};
