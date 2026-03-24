export interface PopoverItem {
  key: string;
  render: (disabled: boolean) => React.ReactNode;
  onSelect: () => void;
  /** When true, the item is already selected — shown dimmed with bg-tint-02. */
  disabled?: boolean;
}

export interface PopoverSection {
  label?: string;
  items: PopoverItem[];
}

export interface ResourcePopoverProps {
  placeholder: string;
  searchValue: string;
  onSearchChange: (value: string) => void;
  sections: PopoverSection[];
}
