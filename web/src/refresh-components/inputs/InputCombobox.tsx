import * as React from "react";
import {
  Popover,
  PopoverTrigger,
  PopoverContent,
} from "@/components/ui/popover";
// If you have a shared Input component, import that instead. Using a basic input below.

type Option = { label: string; value: string };

type InputComboboxProps = {
  value: string | null; // selected value (option.value)
  onChange: (v: string | null) => void; // selection callback
  options: Option[]; // full list
  placeholder?: string;
  allowCustomValue?: boolean; // allow free text submit via Enter
  onCreateOption?: (label: string) => Option | Promise<Option>; // if you want “create”
  className?: string;
  disabled?: boolean;
};

export function InputCombobox({
  value,
  onChange,
  options,
  placeholder = "Type to search…",
  allowCustomValue = false,
  onCreateOption,
  className,
  disabled,
}: InputComboboxProps) {
  const [open, setOpen] = React.useState(false);
  const [query, setQuery] = React.useState("");
  const inputRef = React.useRef<HTMLInputElement | null>(null);
  const listRef = React.useRef<HTMLUListElement | null>(null);
  const [activeIndex, setActiveIndex] = React.useState<number>(-1);

  const selected = options.find((o) => o.value === value) || null;

  // Compute filtered options
  const filtered = React.useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return options;
    return options.filter((o) => o.label.toLowerCase().includes(q));
  }, [options, query]);

  // Keep input text in sync when external selection changes
  React.useEffect(() => {
    // If there’s a selected option and the user hasn’t started typing, show its label.
    if (selected && !open) {
      setQuery(selected.label);
    }
    if (!selected && !open && !query) {
      setQuery("");
    }
  }, [selected, open]); // eslint-disable-line

  // Open when focusing the input
  const handleFocus = () => {
    setOpen(true);
    setActiveIndex(-1);
  };

  const selectAtIndex = async (idx: number) => {
    const opt = filtered[idx];
    if (!opt) return;
    onChange(opt.value);
    setQuery(opt.label);
    setOpen(false);
    // Return focus to the input for good UX
    inputRef.current?.focus();
  };

  const handleEnter = async () => {
    if (activeIndex >= 0 && activeIndex < filtered.length) {
      await selectAtIndex(activeIndex);
      return;
    }
    // Allow custom value creation
    if (allowCustomValue && query.trim()) {
      if (onCreateOption) {
        const created = await onCreateOption(query.trim());
        onChange(created.value);
        setQuery(created.label);
      } else {
        onChange(query.trim());
      }
      setOpen(false);
      inputRef.current?.focus();
    }
  };

  const onKeyDown: React.KeyboardEventHandler<HTMLInputElement> = (e) => {
    if (!open && (e.key === "ArrowDown" || e.key === "Enter")) {
      setOpen(true);
      return;
    }
    switch (e.key) {
      case "ArrowDown":
        e.preventDefault();
        setActiveIndex((i) => Math.min(i + 1, filtered.length - 1));
        break;
      case "ArrowUp":
        e.preventDefault();
        setActiveIndex((i) => Math.max(i - 1, 0));
        break;
      case "Enter":
        e.preventDefault();
        handleEnter();
        break;
      case "Escape":
        setOpen(false);
        break;
    }
  };

  // Close on blur if focus leaves both input and popover
  const onBlurCapture: React.FocusEventHandler<HTMLDivElement> = (e) => {
    // Use a microtask to allow click on an option before closing
    queueMicrotask(() => {
      const root = e.currentTarget;
      if (!root.contains(document.activeElement)) setOpen(false);
    });
  };

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <div className="relative" onBlurCapture={onBlurCapture}>
        <PopoverTrigger asChild>
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              if (!open) setOpen(true);
              setActiveIndex(-1);
            }}
            onFocus={handleFocus}
            onKeyDown={onKeyDown}
            placeholder={placeholder}
            disabled={disabled}
            className={
              "w-full rounded-md border px-3 py-2 outline-none ring-0 focus:border-black/40 " +
              (className ?? "")
            }
            role="combobox"
            aria-controls="combobox-listbox"
            aria-expanded={open}
            aria-autocomplete="list"
            aria-activedescendant={
              activeIndex >= 0 ? `combobox-option-${activeIndex}` : undefined
            }
          />
        </PopoverTrigger>

        <PopoverContent
          align="start"
          className="p-0 w-[min(420px,calc(100vw-2rem))] max-h-64 overflow-auto rounded-md border bg-background"
          onOpenAutoFocus={(e) => e.preventDefault()} // keep focus on input
        >
          {filtered.length === 0 ? (
            <div className="px-3 py-2 text-sm text-muted-foreground">
              No results
              {allowCustomValue && query
                ? ` — press Enter to create “${query}”`
                : ""}
            </div>
          ) : (
            <ul
              ref={listRef}
              id="combobox-listbox"
              role="listbox"
              aria-label="Suggestions"
              className="py-1"
            >
              {filtered.map((opt, idx) => {
                const active = idx === activeIndex;
                const selectedState = opt.value === value;
                return (
                  <li
                    id={`combobox-option-${idx}`}
                    key={opt.value}
                    role="option"
                    aria-selected={active || selectedState}
                    tabIndex={-1}
                    onMouseEnter={() => setActiveIndex(idx)}
                    onMouseDown={(e) => e.preventDefault()} // keep focus on input
                    onClick={() => selectAtIndex(idx)}
                    className={[
                      "cursor-pointer px-3 py-2 text-sm",
                      active ? "bg-accent" : "",
                      selectedState ? "font-medium" : "",
                    ].join(" ")}
                  >
                    {opt.label}
                  </li>
                );
              })}
            </ul>
          )}
        </PopoverContent>
      </div>
    </Popover>
  );
}
