import {
  ChangeEvent,
  FC,
  forwardRef,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import { ChevronDownIcon, PlusIcon } from "./icons/icons";
import { FiCheck, FiChevronDown } from "react-icons/fi";
import { Popover } from "./popover/Popover";

export interface Option<T> {
  name: string;
  value: T;
  description?: string;
  metadata?: { [key: string]: any };
  icon?: React.FC<{ size?: number; className?: string }>;
}

export type StringOrNumberOption = Option<string | number>;

function StandardDropdownOption<T>({
  index,
  option,
  handleSelect,
}: {
  index: number;
  option: Option<T>;
  handleSelect: (option: Option<T>) => void;
}) {
  return (
    <button
      onClick={() => handleSelect(option)}
      className={`w-full text-left block px-4 py-2.5 text-sm bg-white dark:bg-neutral-800 hover:bg-background-50 ${
        index !== 0 ? "border-t border-background-200" : ""
      }`}
      role="menuitem"
    >
      <p className="font-medium  text-xs text-text-900">{option.name}</p>
      {option.description && (
        <p className="text-xs text-text-500">{option.description}</p>
      )}
    </button>
  );
}

export function SearchMultiSelectDropdown({
  options,
  onSelect,
  itemComponent,
  onCreate,
  onDelete,
  onSearchTermChange,
  initialSearchTerm = "",
  allowCustomValues = false,
}: {
  options: StringOrNumberOption[];
  onSelect: (selected: StringOrNumberOption) => void;
  itemComponent?: FC<{ option: StringOrNumberOption }>;
  onCreate?: (name: string) => void;
  onDelete?: (name: string) => void;
  onSearchTermChange?: (term: string) => void;
  initialSearchTerm?: string;
  allowCustomValues?: boolean;
}) {
  const [isOpen, setIsOpen] = useState(false);
  const [searchTerm, setSearchTerm] = useState(initialSearchTerm);
  const dropdownRef = useRef<HTMLDivElement>(null);

  const handleSelect = (option: StringOrNumberOption) => {
    onSelect(option);
    setIsOpen(false);
    setSearchTerm(""); // Clear search term after selection
  };

  const filteredOptions = options.filter((option) =>
    option.name.toLowerCase().includes(searchTerm.toLowerCase())
  );

  // Handle selecting a custom value not in the options list
  const handleCustomValueSelect = () => {
    if (allowCustomValues && searchTerm.trim() !== "") {
      const customOption: StringOrNumberOption = {
        name: searchTerm,
        value: searchTerm,
      };
      onSelect(customOption);
      setIsOpen(false);
    }
  };

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (
        dropdownRef.current &&
        !dropdownRef.current.contains(event.target as Node)
      ) {
        // If allowCustomValues is enabled and there's text in the search field,
        // treat clicking outside as selecting the custom value
        if (allowCustomValues && searchTerm.trim() !== "") {
          handleCustomValueSelect();
        }
        setIsOpen(false);
      }
    };

    document.addEventListener("mousedown", handleClickOutside);
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, [allowCustomValues, searchTerm]);

  useEffect(() => {
    setSearchTerm(initialSearchTerm);
  }, [initialSearchTerm]);

  return (
    <div className="relative text-left w-full" ref={dropdownRef}>
      <div>
        <input
          type="text"
          placeholder={
            allowCustomValues ? "Search or enter custom value..." : "Search..."
          }
          value={searchTerm}
          onChange={(e: ChangeEvent<HTMLInputElement>) => {
            const newValue = e.target.value;
            setSearchTerm(newValue);
            if (onSearchTermChange) {
              onSearchTermChange(newValue);
            }
            if (newValue) {
              setIsOpen(true);
            } else {
              setIsOpen(false);
            }
          }}
          onFocus={() => setIsOpen(true)}
          onKeyDown={(e) => {
            if (
              e.key === "Enter" &&
              allowCustomValues &&
              searchTerm.trim() !== ""
            ) {
              e.preventDefault();
              handleCustomValueSelect();
            }
          }}
          className="inline-flex justify-between w-full px-4 py-2 text-sm bg-white dark:bg-transparent text-text-800 border border-background-300 rounded-md shadow-sm"
        />
        <button
          type="button"
          className="absolute top-0 right-0 text-sm h-full px-2 border-l border-background-300"
          aria-expanded={isOpen}
          aria-haspopup="true"
          onClick={() => setIsOpen(!isOpen)}
        >
          <ChevronDownIcon className="my-auto w-4 h-4 text-text-600" />
        </button>
      </div>

      {isOpen && (
        <div className="absolute z-10 mt-1 w-full rounded-md shadow-lg bg-white border border-background-300 max-h-60 overflow-y-auto">
          <div
            role="menu"
            aria-orientation="vertical"
            aria-labelledby="options-menu"
          >
            {filteredOptions.map((option, index) =>
              itemComponent ? (
                <div
                  key={option.name}
                  onClick={() => {
                    handleSelect(option);
                  }}
                >
                  {itemComponent({ option })}
                </div>
              ) : (
                <StandardDropdownOption
                  key={index}
                  option={option}
                  index={index}
                  handleSelect={handleSelect}
                />
              )
            )}

            {allowCustomValues &&
              searchTerm.trim() !== "" &&
              !filteredOptions.some(
                (option) =>
                  option.name.toLowerCase() === searchTerm.toLowerCase()
              ) && (
                <button
                  className="w-full text-left flex items-center px-4 py-2 text-sm text-text-800 hover:bg-background-100"
                  role="menuitem"
                  onClick={handleCustomValueSelect}
                >
                  <PlusIcon className="w-4 h-4 mr-2 text-text-600" />
                  Use &quot;{searchTerm}&quot; as custom value
                </button>
              )}

            {onCreate &&
              searchTerm.trim() !== "" &&
              !filteredOptions.some(
                (option) =>
                  option.name.toLowerCase() === searchTerm.toLowerCase()
              ) && (
                <>
                  <div className="border-t border-background-300"></div>
                  <button
                    className="w-full text-left flex items-center px-4 py-2 text-sm text-text-800 hover:bg-background-100"
                    role="menuitem"
                    onClick={() => {
                      onCreate(searchTerm);
                      setIsOpen(false);
                      setSearchTerm("");
                    }}
                  >
                    <PlusIcon className="w-4 h-4 mr-2 text-text-600" />
                    Create label &quot;{searchTerm}&quot;
                  </button>
                </>
              )}

            {filteredOptions.length === 0 &&
              ((!onCreate && !allowCustomValues) ||
                searchTerm.trim() === "") && (
                <div className="px-4 py-2.5 text-sm text-text-500">
                  No matches found
                </div>
              )}
          </div>
        </div>
      )}
    </div>
  );
}

export const CustomDropdown = ({
  children,
  dropdown,
  direction = "down",
}: {
  children: JSX.Element | string;
  dropdown: JSX.Element | string;
  direction?: "up" | "down";
}) => {
  const [isOpen, setIsOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (
        dropdownRef.current &&
        !dropdownRef.current.contains(event.target as Node)
      ) {
        setIsOpen(false);
      }
    };

    document.addEventListener("mousedown", handleClickOutside);
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, []);

  return (
    <div className="relative inline-block text-left w-full" ref={dropdownRef}>
      <div onClick={() => setIsOpen(!isOpen)}>{children}</div>

      {isOpen && (
        <div
          onClick={() => setIsOpen(!isOpen)}
          className={`absolute ${
            direction === "up" ? "bottom-full pb-2" : "pt-2"
          } w-full z-30 box-shadow`}
        >
          {dropdown}
        </div>
      )}
    </div>
  );
};

export function DefaultDropdownElement({
  name,
  icon,
  description,
  onSelect,
  isSelected,
  includeCheckbox = false,
}: {
  name: string | JSX.Element;
  icon?: React.FC<{ size?: number; className?: string }>;
  description?: string;
  onSelect?: () => void;
  isSelected?: boolean;
  includeCheckbox?: boolean;
}) {
  return (
    <div
      className={`
        flex
        mx-1
        px-2
        text-sm 
        py-1.5 
        my-1
        select-none 
        cursor-pointer 
        bg-transparent 
        rounded
        text-text-dark
        hover:bg-accent-background-hovered
      `}
      onClick={onSelect}
    >
      <div>
        <div className="flex">
          {includeCheckbox && (
            <input
              type="checkbox"
              className="mr-2"
              checked={isSelected}
              onChange={() => null}
            />
          )}
          {icon && icon({ size: 16, className: "mr-2 h-4 w-4 my-auto" })}
          {name}
        </div>
        {description && <div className="text-xs">{description}</div>}
      </div>
      {isSelected && (
        <div className="ml-auto mr-1 my-auto">
          <FiCheck />
        </div>
      )}
    </div>
  );
}

type DefaultDropdownProps = {
  options: StringOrNumberOption[];
  selected: string | null;
  onSelect: (value: string | number | null) => void;
  includeDefault?: boolean;
  defaultValue?: string;
  side?: "top" | "right" | "bottom" | "left";
  maxHeight?: string;
};

export const DefaultDropdown = forwardRef<HTMLDivElement, DefaultDropdownProps>(
  (
    {
      options,
      selected,
      onSelect,
      includeDefault,
      defaultValue,
      side,
      maxHeight,
    },
    ref
  ) => {
    const selectedOption = options.find((option) => option.value === selected);
    const [isOpen, setIsOpen] = useState(false);

    const handleSelect = (value: any) => {
      onSelect(value);
      setIsOpen(false);
    };

    const Content = (
      <div
        className={`
          flex 
          text-sm 
          bg-background 
          px-3
          py-1.5 
          rounded-lg 
          border 
          border-border 
          cursor-pointer`}
      >
        <p className="line-clamp-1">
          {selectedOption?.name ||
            (includeDefault
              ? defaultValue || "Default"
              : "Select an option...")}
        </p>
        <FiChevronDown className="my-auto ml-auto" />
      </div>
    );

    const Dropdown = (
      <div
        ref={ref}
        className={`
        border 
        border 
        rounded-lg 
        flex 
        flex-col 
        bg-background
        ${maxHeight || "max-h-96"}
        overflow-y-auto 
        overscroll-contain`}
      >
        {includeDefault && (
          <DefaultDropdownElement
            key={-1}
            name="Default"
            onSelect={() => handleSelect(null)}
            isSelected={selected === null}
          />
        )}
        {options.map((option, ind) => {
          const isSelected = option.value === selected;
          return (
            <DefaultDropdownElement
              key={option.value}
              name={option.name}
              description={option.description}
              onSelect={() => handleSelect(option.value)}
              isSelected={isSelected}
              icon={option.icon}
            />
          );
        })}
      </div>
    );

    return (
      <div onClick={() => setIsOpen(!isOpen)}>
        <Popover
          open={isOpen}
          onOpenChange={(open) => setIsOpen(open)}
          content={Content}
          popover={Dropdown}
          align="start"
          side={side}
          sideOffset={5}
          matchWidth
          triggerMaxWidth
        />
      </div>
    );
  }
);

export function ControlledPopup({
  children,
  popupContent,
  isOpen,
  setIsOpen,
}: {
  children: JSX.Element | string;
  popupContent: JSX.Element | string;
  isOpen: boolean;
  setIsOpen: (value: boolean) => void;
}) {
  const filtersRef = useRef<HTMLDivElement>(null);
  // hides logout popup on any click outside
  const handleClickOutside = useCallback(
    (event: MouseEvent) => {
      if (
        filtersRef.current &&
        !filtersRef.current.contains(event.target as Node)
      ) {
        setIsOpen(false);
      }
    },
    [filtersRef, setIsOpen]
  );

  useEffect(() => {
    document.addEventListener("mousedown", handleClickOutside);

    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, [handleClickOutside]);

  return (
    <div ref={filtersRef} className="relative">
      {children}
      {isOpen && (
        <div
          className={`
            absolute 
            top-0 
            bg-background 
            border 
            border-border 
            z-30 
            rounded 
            text-text-darker 
            shadow-lg`}
          style={{ transform: "translateY(calc(-100% - 5px))" }}
        >
          {popupContent}
        </div>
      )}
    </div>
  );
}
DefaultDropdown.displayName = "DefaultDropdown";
