import { CheckmarkIcon } from "./icons/icons";

export const CustomCheckbox = ({
  checked,
  onChange,
}: {
  checked: boolean;
  onChange?: () => void;
}) => {
  return (
    <label className="flex items-center cursor-pointer">
      <input
        type="checkbox"
        className="hidden"
        checked={checked}
        onChange={onChange}
        readOnly={onChange ? false : true}
      />
      <span className="relative">
        <span
          className={`block w-3 h-3 border border-border-strong rounded ${
            checked ? "bg-green-700" : "bg-background"
          } transition duration-300`}
        >
          {checked && (
            <CheckmarkIcon
              size={12}
              className="absolute top-0 left-0 fill-current text-inverted"
            />
          )}
        </span>
      </span>
    </label>
  );
};
