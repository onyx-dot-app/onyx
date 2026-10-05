import { Dropdown, type InputDateRangePickerValue } from "@opal/components";
import { useTranslations } from "next-intl";
import { FiCalendar, FiChevronDown, FiXCircle } from "react-icons/fi";
import { timeRangeValues } from "@/app/config/timeRange";

export function SearchDateRangeSelector({
  value,
  onValueChange,
  isHorizontal,
}: {
  value: InputDateRangePickerValue | null;
  onValueChange: (value: InputDateRangePickerValue | null) => void;
  isHorizontal?: boolean;
  className?: string;
}) {
  const t = useTranslations("common.dateRange");
  return (
    <div>
      <Dropdown>
        <Dropdown.Trigger asChild>
          {/* A focusable trigger; the clear control inside is its own button. */}
          <div
            role="button"
            tabIndex={0}
            className={`
            flex
            text-sm
            px-3
            line-clamp-1
            py-1.5
            rounded-lg
            border
            border-border
            cursor-pointer
            hover:bg-accent-background-hovered`}
          >
            <FiCalendar className="flex-none my-auto me-2" />{" "}
            <p className="line-clamp-1">
              {isHorizontal ? (
                t("date.label")
              ) : value?.selectValue ? (
                <div className="text-text-darker">{value.selectValue}</div>
              ) : (
                t("anyTime.text")
              )}
            </p>
            {value?.selectValue ? (
              <button
                type="button"
                aria-label={t("clearButton.ariaLabel")}
                className="my-auto ms-auto p-0.5 rounded-full w-fit"
                onClick={(e) => {
                  onValueChange(null);
                  e.stopPropagation();
                }}
              >
                <FiXCircle />
              </button>
            ) : (
              <FiChevronDown className="my-auto ms-auto" />
            )}
          </div>
        </Dropdown.Trigger>
        <Dropdown.Data
          label={t("date.label")}
          value={value?.selectValue ?? ""}
          onSelect={(option) => {
            const preset = timeRangeValues.find(
              (range) => range.label === option.value
            );
            if (!preset) return;
            onValueChange({
              to: new Date(),
              from: preset.value,
              selectValue: preset.label,
            });
          }}
          items={timeRangeValues.map((range) => ({
            kind: "option",
            value: range.label,
            title: range.label,
          }))}
        />
      </Dropdown>
    </div>
  );
}
