import { DefaultDropdownElement } from "../Dropdown";
export function TimeRangeSelector({
  value,
  onValueChange,
  className,
  timeRangeValues,
}: {
  value: any;
  onValueChange: any;
  className: any;

  timeRangeValues: { label: string; value: Date }[];
}) {
  return (
    <div className={className}>
      {timeRangeValues.map((timeRangeValue) => (
        <DefaultDropdownElement
          key={timeRangeValue.label}
          name={timeRangeValue.label}
          onSelect={() =>
            onValueChange({
              to: new Date(),
              from: timeRangeValue.value,
              selectValue: timeRangeValue.label,
            })
          }
          isSelected={value?.selectValue === timeRangeValue.label}
        />
      ))}
    </div>
  );
}
