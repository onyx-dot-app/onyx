import {
  PageSelector,
  type PageSelectorProps as Props,
} from "@/components/PageSelector";

const CenteredPageSelector = ({
  currentPage,
  totalPages,
  onPageChange,
}: Props) => (
  <div className="mx-auto text-center">
    <PageSelector
      currentPage={currentPage}
      totalPages={totalPages}
      onPageChange={onPageChange}
    />
  </div>
);

export default CenteredPageSelector;
