import { FiCheck, FiChevronDown, FiXCircle } from "react-icons/fi";
import { CustomDropdown } from "../../Dropdown";

interface Option {
  key: string;
  display: string | JSX.Element;
  displayName?: string;
  icon?: JSX.Element;
}
export function FilterDropdown({
  options,
  selected,
  handleSelect,
  icon,
  defaultDisplay,
  width = "w-64",
  dropdownWidth,
  optionClassName,
  resetValues,
  backgroundColor,
  dropdownColor,
}: {
  options: Option[];
  selected: string[];
  handleSelect: (option: Option) => void;
  icon: JSX.Element;
  defaultDisplay: string | JSX.Element;
  width?: string;
  dropdownWidth?: string;
  optionClassName?: string;
  resetValues?: () => void;
  backgroundColor?: string;
  dropdownColor?: string;
}) {
  return (
    <div>
      <CustomDropdown
        dropdown={
          <div
            className={`
              border 
              border-border 
              rounded-lg 
              ${backgroundColor || "bg-background"}
              flex 
              flex-col 
              ${dropdownWidth || width}
              max-h-96 
              overflow-y-scroll
              overscroll-contain
              `}
          >
            {options.map((option, ind) => {
              const isSelected = selected.includes(option.key);
              return (
                <div
                  key={`${option.key}-1`}
                  className={`
                      ${optionClassName}
                      flex
                      px-3
                      text-sm
                      py-2.5
                      select-none
                      cursor-pointer
                      flex-none
                      w-full
                      text-text-darker
                      items-center
                      gap-x-1
                      ${dropdownColor || "bg-background"}
                      hover:bg-accent-background-hovered
                      ${
                        ind === options.length - 1
                          ? ""
                          : "border-b border-border"
                      } 
                    `}
                  onClick={(event) => {
                    handleSelect(option);
                    event.preventDefault();
                    event.stopPropagation();
                  }}
                >
                  {option.icon}
                  {option.display}
                  {isSelected && (
                    <div className="ml-auto my-auto mr-1">
                      <FiCheck />
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        }
      >
        <div
          className={`
            flex
            ${width}
            text-sm
            px-3
            py-1.5
            rounded-lg 
            border 
            gap-x-2
            border-border
            cursor-pointer 
            ${backgroundColor || "bg-background"}
            hover:bg-accent-background`}
        >
          <div className="flex-none my-auto">{icon}</div>
          {selected.length === 0 || resetValues ? (
            defaultDisplay
          ) : (
            <p className="line-clamp-1">{selected.join(", ")}</p>
          )}
          {resetValues && selected.length !== 0 ? (
            <div
              className="my-auto ml-auto p-0.5 rounded-full w-fit"
              onClick={(e) => {
                resetValues();
                e.stopPropagation();
              }}
            >
              <FiXCircle />
            </div>
          ) : (
            <FiChevronDown className="my-auto ml-auto" />
          )}
        </div>
      </CustomDropdown>
    </div>
  );
}
