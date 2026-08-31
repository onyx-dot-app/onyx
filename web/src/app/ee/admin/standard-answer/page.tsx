"use client";

import { useAdminRouteTitle } from "@/lib/adminNavLabels";
import { useTranslations } from "next-intl";
import { SettingsLayouts, toast } from "@opal/layouts";
import { useStandardAnswers, useStandardAnswerCategories } from "./hooks";
import { PageLoader } from "@opal/layouts";
import { ErrorCallout } from "@/components/ErrorCallout";
import { Divider } from "@opal/components";
import {
  Table,
  TableHead,
  TableRow,
  TableBody,
  TableCell,
} from "@/components/ui/table";

import Link from "next/link";
import type { Route } from "next";
import { StandardAnswer, StandardAnswerCategory } from "@/lib/types";
import { SvgSearch } from "@opal/icons";
import { useState, JSX } from "react";
import { useFocusOnMount } from "@opal/hooks";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { deleteStandardAnswer } from "./lib";
import { FilterDropdown } from "@/components/search/filtering/FilterDropdown";
import { FiTag } from "react-icons/fi";
import { PageSelector } from "@/components/PageSelector";
import { Text } from "@opal/components";
import { cn, clickOnKeyDown, markdown } from "@opal/utils";
import { Spacer } from "@opal/components";
import { TableHeader } from "@/components/ui/table";
import { SvgEdit, SvgPlusCircle, SvgTrash } from "@opal/icons";
import { Button } from "@opal/components";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
const NUM_RESULTS_PER_PAGE = 10;

const route = ADMIN_ROUTES.STANDARD_ANSWERS;

type Displayable = JSX.Element | string;

const RowTemplate = ({
  id,
  entries,
}: {
  id: number;
  entries: [
    Displayable,
    Displayable,
    Displayable,
    Displayable,
    Displayable,
    Displayable,
  ];
}) => {
  return (
    <TableRow key={id}>
      <TableCell className="w-1/24">{entries[0]}</TableCell>
      <TableCell className="w-2/12">{entries[1]}</TableCell>
      <TableCell className="w-2/12">{entries[2]}</TableCell>
      <TableCell className="w-1/24">{entries[3]}</TableCell>
      <TableCell className="w-7/12 overflow-auto">{entries[4]}</TableCell>
      <TableCell className="w-1/24">{entries[5]}</TableCell>
    </TableRow>
  );
};

const CategoryBubble = ({
  name,
  onDelete,
}: {
  name: string;
  onDelete?: () => void;
}) => {
  const t = useTranslations("admin.standardAnswers");
  const adminRouteTitle = useAdminRouteTitle();
  const className = cn(
    "inline-block px-2 py-1 me-1 mb-1 text-xs font-semibold text-emphasis bg-accent-background-hovered rounded-full items-center w-fit",
    onDelete && "cursor-pointer"
  );

  if (!onDelete) return <span className={className}>{name}</span>;

  return (
    // The bubble holds its own remove button, so it stays a span with button
    // semantics rather than a <button> wrapping a <button>.
    <span
      className={className}
      role="button"
      tabIndex={0}
      aria-label={t("categoryBubble.remove.ariaLabel", { name })}
      onKeyDown={clickOnKeyDown(onDelete)}
      onClick={onDelete}
    >
      {name}
      <button
        className="ms-1 text-subtle hover:text-emphasis"
        aria-label={t("categoryBubble.removeButton.ariaLabel")}
      >
        &times;
      </button>
    </span>
  );
};

const StandardAnswersTableRow = ({
  standardAnswer,
  handleDelete,
}: {
  standardAnswer: StandardAnswer;
  handleDelete: (id: number) => void;
}) => {
  const t = useTranslations("admin.standardAnswers");
  const adminRouteTitle = useAdminRouteTitle();
  return (
    <RowTemplate
      id={standardAnswer.id}
      entries={[
        <Link
          key={`edit-${standardAnswer.id}`}
          href={`/ee/admin/standard-answer/${standardAnswer.id}` as Route}
        >
          <SvgEdit size={16} />
        </Link>,
        <div key={`categories-${standardAnswer.id}`}>
          {standardAnswer.categories.map((category) => (
            <CategoryBubble key={category.id} name={category.name} />
          ))}
        </div>,
        <ReactMarkdown key={`keyword-${standardAnswer.id}`}>
          {standardAnswer.match_regex
            ? `\`${standardAnswer.keyword}\``
            : standardAnswer.keyword}
        </ReactMarkdown>,
        <div
          key={`match_regex-${standardAnswer.id}`}
          className="flex items-center"
        >
          {standardAnswer.match_regex ? (
            <span className="text-green-500 font-medium">
              {t("table.matchRegexYes.label")}
            </span>
          ) : (
            <span className="text-gray-500">
              {t("table.matchRegexNo.label")}
            </span>
          )}
        </div>,
        <ReactMarkdown
          key={`answer-${standardAnswer.id}`}
          className="prose dark:prose-invert"
          remarkPlugins={[remarkGfm]}
        >
          {standardAnswer.answer}
        </ReactMarkdown>,
        <Button
          key={`delete-${standardAnswer.id}`}
          icon={SvgTrash}
          onClick={() => handleDelete(standardAnswer.id)}
        />,
      ]}
    />
  );
};

const StandardAnswersTable = ({
  standardAnswers,
  standardAnswerCategories,
  refresh,
}: {
  standardAnswers: StandardAnswer[];
  standardAnswerCategories: StandardAnswerCategory[];
  refresh: () => void;
}) => {
  const t = useTranslations("admin.standardAnswers");
  const adminRouteTitle = useAdminRouteTitle();
  const [query, setQuery] = useState("");
  const [currentPage, setCurrentPage] = useState(1);
  const [selectedCategories, setSelectedCategories] = useState<
    StandardAnswerCategory[]
  >([]);
  const focusOnMount = useFocusOnMount<HTMLTextAreaElement>();
  const columns = [
    { name: "", key: "edit" },
    { name: t("table.categories.header"), key: "category" },
    { name: t("table.keywords.header"), key: "keyword" },
    { name: t("table.matchRegex.header"), key: "match_regex" },
    { name: t("table.answer.header"), key: "answer" },
    { name: "", key: "delete" },
  ];

  const filteredStandardAnswers = standardAnswers.filter((standardAnswer) => {
    const {
      answer,
      id,
      categories,
      match_regex,
      match_any_keywords,
      ...fieldsToSearch
    } = standardAnswer;
    const cleanedQuery = query.toLowerCase();
    const searchMatch = Object.values(fieldsToSearch).some((value) => {
      return value.toLowerCase().includes(cleanedQuery);
    });
    const categoryMatch =
      selectedCategories.length == 0 ||
      selectedCategories.some((category) =>
        categories.map((c) => c.id).includes(category.id)
      );
    return searchMatch && categoryMatch;
  });

  const totalPages = Math.ceil(
    filteredStandardAnswers.length / NUM_RESULTS_PER_PAGE
  );
  const startIndex = (currentPage - 1) * NUM_RESULTS_PER_PAGE;
  const endIndex = startIndex + NUM_RESULTS_PER_PAGE;
  const paginatedStandardAnswers = filteredStandardAnswers.slice(
    startIndex,
    endIndex
  );

  const handlePageChange = (page: number) => {
    setCurrentPage(page);
  };

  const handleDelete = async (id: number) => {
    const response = await deleteStandardAnswer(id);
    if (response.ok) {
      toast.success(t("toasts.deleted.message", { id }));
    } else {
      const errorMsg = await response.text();
      toast.error(t("toasts.deleteFailed.message", { error: errorMsg }));
    }
    refresh();
  };

  const handleCategorySelect = (category: StandardAnswerCategory) => {
    setSelectedCategories((prev: StandardAnswerCategory[]) => {
      const prevCategoryIds = prev.map((category) => category.id);
      if (prevCategoryIds.includes(category.id)) {
        return prev.filter((c) => c.id !== category.id);
      }
      return [...prev, category];
    });
  };

  return (
    <div className="justify-center py-2">
      <div className="flex items-center w-full border-2 border-border rounded-lg px-4 py-2 focus-within:border-accent">
        <SvgSearch className="w-4 h-4" />
        <textarea
          ref={focusOnMount}
          className="grow ms-2 h-6 bg-transparent outline-hidden placeholder-subtle overflow-hidden whitespace-normal resize-none"
          placeholder={t("search.placeholder")}
          value={query}
          onChange={(event) => {
            setQuery(event.target.value);
            setCurrentPage(1);
          }}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
            }
          }}
          suppressContentEditableWarning={true}
        />
      </div>
      <div className="my-4 border-b border-border">
        <FilterDropdown
          options={standardAnswerCategories.map((category) => {
            return {
              key: category.name,
              display: category.name,
            };
          })}
          selected={selectedCategories.map((category) => category.name)}
          handleSelect={(option) => {
            handleCategorySelect(
              standardAnswerCategories.find(
                (category) => category.name === option.key
              )!
            );
          }}
          icon={
            <div className="my-auto me-2 w-[16px] h-[16px]">
              <FiTag size={16} />
            </div>
          }
          defaultDisplay={t("filter.allCategories.label")}
        />
        <div className="flex flex-wrap pb-4 mt-3">
          {selectedCategories.map((category) => (
            <CategoryBubble
              key={category.id}
              name={category.name}
              onDelete={() => handleCategorySelect(category)}
            />
          ))}
        </div>
      </div>
      <div className="flex flex-col w-full mx-auto">
        <Table className="w-full">
          <TableHeader>
            <TableRow>
              {columns.map((column) => (
                <TableHead key={column.key}>{column.name}</TableHead>
              ))}
            </TableRow>
          </TableHeader>

          <TableBody>
            {paginatedStandardAnswers.length > 0 ? (
              paginatedStandardAnswers.map((item) => (
                <StandardAnswersTableRow
                  key={item.id}
                  standardAnswer={item}
                  handleDelete={handleDelete}
                />
              ))
            ) : (
              <RowTemplate id={0} entries={["", "", "", "", "", ""]} />
            )}
          </TableBody>
        </Table>
        <div>
          {paginatedStandardAnswers.length === 0 && (
            <div className="flex justify-center">
              <Text as="p">{t("table.empty.message")}</Text>
            </div>
          )}
        </div>
        {paginatedStandardAnswers.length > 0 && (
          <>
            <div className="mt-4">
              <Text as="p">{markdown(t("table.slackNote.message"))}</Text>
            </div>
            <div className="mt-4 flex justify-center">
              <PageSelector
                currentPage={currentPage}
                totalPages={totalPages}
                onPageChange={handlePageChange}
                shouldScroll={true}
              />
            </div>
          </>
        )}
      </div>
    </div>
  );
};

function Main() {
  const t = useTranslations("admin.standardAnswers");
  const adminRouteTitle = useAdminRouteTitle();
  const {
    data: standardAnswers,
    error: standardAnswersError,
    isLoading: standardAnswersIsLoading,
    refreshStandardAnswers,
  } = useStandardAnswers();
  const {
    data: standardAnswerCategories,
    error: standardAnswerCategoriesError,
    isLoading: standardAnswerCategoriesIsLoading,
  } = useStandardAnswerCategories();

  if (standardAnswersIsLoading || standardAnswerCategoriesIsLoading) {
    return <PageLoader />;
  }

  if (standardAnswersError || !standardAnswers) {
    return (
      <ErrorCallout
        errorTitle={t("errors.loadAnswersFailed.title")}
        errorMsg={
          standardAnswersError.info?.detail ||
          standardAnswersError.info?.message
        }
      />
    );
  }

  if (standardAnswerCategoriesError || !standardAnswerCategories) {
    return (
      <ErrorCallout
        errorTitle={t("errors.loadCategoriesFailed.title")}
        errorMsg={
          standardAnswerCategoriesError.info?.detail ||
          standardAnswerCategoriesError.info?.message
        }
      />
    );
  }

  return (
    <div className="mb-8">
      <Text as="p">{markdown(t("intro.description"))}</Text>
      <Spacer rem={0.5} />
      {standardAnswers.length == 0 && (
        <>
          <Text as="p">{t("intro.addFirst.message")}</Text>
          <Spacer rem={0.5} />
        </>
      )}
      <div className="mb-2"></div>

      <Button
        icon={SvgPlusCircle}
        prominence="secondary"
        href="/admin/standard-answer/new"
      >
        {t("newStandardAnswer.label")}
      </Button>

      <Divider />

      <div>
        <StandardAnswersTable
          standardAnswers={standardAnswers}
          standardAnswerCategories={standardAnswerCategories}
          refresh={refreshStandardAnswers}
        />
      </div>
    </div>
  );
}

export default function Page() {
  const adminRouteTitle = useAdminRouteTitle();
  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        icon={route.icon}
        title={adminRouteTitle(route)}
        divider
      />
      <SettingsLayouts.Body>
        <Main />
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
