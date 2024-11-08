import * as React from "react";
import { ChevronsUpDown, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { Badge } from "@/components/ui/badge";
import { Separator } from "./ui/separator";
import { CustomTooltip } from "./CustomTooltip";

interface ComboboxProps {
  items: { value: string; label: string }[] | undefined;
  onSelect?: (selectedValue: string[]) => void;
  placeholder?: string;
  label?: string;
  selected?: string[];
}

export function Combobox({
  items,
  onSelect,
  placeholder = "Select an item...",
  label = "Select item",
  selected = [],
}: ComboboxProps) {
  const [open, setOpen] = React.useState(false);
  const [selectedItems, setSelectedItems] = React.useState<
    { value: string; label: string }[]
  >(items?.filter((item) => selected.includes(item.value)) || []);

  const handleSelect = (currentValue: string) => {
    const selectedItem = items?.find((item) => item.label === currentValue);
    if (
      selectedItem &&
      !selectedItems.some((item) => item.value === selectedItem.value)
    ) {
      const newSelectedItems = [...selectedItems, selectedItem];
      setSelectedItems(newSelectedItems);
      if (onSelect) {
        onSelect(newSelectedItems.map((item) => item.value));
      }
    }
    setOpen(false);
  };

  const handleRemove = (value: string) => {
    const updatedSelectedItems = selectedItems.filter(
      (item) => item.value !== value
    );
    setSelectedItems(updatedSelectedItems);
    if (onSelect) {
      onSelect(updatedSelectedItems.map((item) => item.value));
    }
  };

  const handleSelectAll = () => {
    if (items) {
      setSelectedItems(items);
      if (onSelect) {
        onSelect(items.map((item) => item.value));
      }
      setOpen(false);
    }
  };

  const filteredItems = items?.filter(
    (item) => !selectedItems.some((selected) => selected.value === item.value)
  );

  return (
    <>
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button
            variant="outline"
            role="combobox"
            aria-expanded={open}
            className="justify-between w-full border text-subtle border-input"
          >
            {selectedItems.length > 0
              ? `${selectedItems.length} selected`
              : label}
            <ChevronsUpDown className="w-4 h-4 ml-2 opacity-50 shrink-0" />
          </Button>
        </PopoverTrigger>
        <PopoverContent
          className="min-w-[300px] sm:min-w-[495px] md:min-w-[550px] lg:min-w-[495px] xl:min-w-[625px]"
          align="start"
        >
          <Command>
            <CommandInput
              placeholder={`Search ${placeholder.toLowerCase()}...`}
            />
            <CommandList>
              <CommandEmpty>No items found.</CommandEmpty>
              <CommandGroup>
                <CommandItem onSelect={handleSelectAll}>Select All</CommandItem>
              </CommandGroup>
              <Separator />
              <CommandGroup>
                {filteredItems?.map((item) => (
                  <CommandItem
                    key={item.value}
                    value={item.label}
                    onSelect={() => handleSelect(item.label)}
                  >
                    {item.label}
                  </CommandItem>
                ))}
              </CommandGroup>
            </CommandList>
          </Command>
        </PopoverContent>
      </Popover>

      {/* Selected items badges */}
      {selectedItems.length > 0 && (
        <div className="flex flex-wrap gap-2 pt-2">
          {selectedItems.map((selectedItem) => (
            <CustomTooltip
              key={selectedItem.value}
              trigger={
                <Badge
                  onClick={() => handleRemove(selectedItem.value)}
                  variant="outline"
                  className="cursor-pointer hover:bg-blue-200"
                >
                  <p className="truncate w-full">{selectedItem.label}</p>
                  <X className="my-auto ml-1 cursor-pointer" size={14} />
                </Badge>
              }
            >
              {selectedItem.label}
            </CustomTooltip>
          ))}
        </div>
      )}
    </>
  );
}