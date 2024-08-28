"use client";

import { AdminPageTitle } from "@/components/admin/Title";
import { ClipboardIcon, EditIcon, TrashIcon } from "@/components/icons/icons";
import { PopupSpec, usePopup } from "@/components/admin/connectors/Popup";
import { useStandardAnswers, useStandardAnswerCategories } from "./hooks";
import { ThreeDotsLoader } from "@/components/Loading";
import { ErrorCallout } from "@/components/ErrorCallout";
import { Button, Divider, Text } from "@tremor/react";
import Link from "next/link";
import { StandardAnswer, StandardAnswerCategory } from "@/lib/types";
import { MagnifyingGlass } from "@phosphor-icons/react";
import { useState } from "react";
import {
  Table,
  TableHead,
  TableRow,
  TableHeaderCell,
  TableBody,
  TableCell,
} from "@tremor/react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { deleteStandardAnswer } from "./lib";
import { FilterDropdown } from "@/components/search/filtering/FilterDropdown";
import { FiTag } from "react-icons/fi";
import { SelectedBubble } from "@/components/search/filtering/Filters";
import { PageSelector } from "@/components/PageSelector";

const NUM_RESULTS_PER_PAGE = 10;

type Displayable = JSX.Element | string;

const RowTemplate = ({
  id,
  entries,
}: {
  id: number;
  entries: [Displayable, Displayable, Displayable, Displayable, Displayable];
}) => {
  return (
    <TableRow key={id}>
      <TableCell className="w-1/24">{entries[0]}</TableCell>
      <TableCell className="w-2/12">{entries[1]}</TableCell>
      <TableCell className="w-2/12">{entries[2]}</TableCell>
      <TableCell className="w-7/12 overflow-auto">{entries[3]}</TableCell>
      <TableCell className="w-1/24">{entries[4]}</TableCell>
    </TableRow>
  );
};

const CategoryBubble = ({
  name,
  onDelete,
}: {
  name: string;
  onDelete?: () => void;
}) => (
  <span
    className={`
      inline-block
      px-2
      py-1
      mr-1
      mb-1
      text-xs
      font-semibold
      text-emphasis
      bg-hover
      rounded-full
      items-center
      w-fit
      ${onDelete ? "cursor-pointer" : ""}
    `}
    onClick={onDelete}
  >
    {name}
    {onDelete && (
      <button
        className="ml-1 text-subtle hover:text-emphasis"
        aria-label="Remove category"
      >
        &times;
      </button>
    )}
  </span>
);

const StandardAnswersTableRow = ({
  standardAnswer,
  handleDelete,
}: {
  standardAnswer: StandardAnswer;
  handleDelete: (id: number) => void;
}) => {
  return (
    <RowTemplate
      id={standardAnswer.id}
      entries={[
        <Link
          key={`edit-${standardAnswer.id}`}
          href={`/admin/standard-answer/${standardAnswer.id}`}
        >
          <EditIcon />
        </Link>,
        <div key={`categories-${standardAnswer.id}`}>
          {standardAnswer.categories.map((category) => (
            <CategoryBubble key={category.id} name={category.name} />
          ))}
        </div>,
        standardAnswer.keyword,
        <ReactMarkdown
          key={`answer-${standardAnswer.id}`}
          className="prose"
          remarkPlugins={[remarkGfm]}
        >
          {standardAnswer.answer}
        </ReactMarkdown>,
        <div
          key={`delete-${standardAnswer.id}`}
          className="cursor-pointer"
          onClick={() => handleDelete(standardAnswer.id)}
        >
          <TrashIcon />
        </div>,
      ]}
    />
  );
};

const StandardAnswersTable = ({
  standardAnswers,
  standardAnswerCategories,
  refresh,
  setPopup,
}: {
  standardAnswers: StandardAnswer[];
  standardAnswerCategories: StandardAnswerCategory[];
  refresh: () => void;
  setPopup: (popup: PopupSpec | null) => void;
}) => {
  const [query, setQuery] = useState("");
  const [currentPage, setCurrentPage] = useState(1);
  const [selectedCategories, setSelectedCategories] = useState<
    StandardAnswerCategory[]
  >([]);
  const columns = [
    { name: "", key: "edit" },
    { name: "Categories", key: "category" },
    { name: "Keyword/Phrase", key: "keyword" },
    { name: "Answer", key: "answer" },
    { name: "", key: "delete" },
  ];

  const filteredStandardAnswers = standardAnswers.filter((standardAnswer) => {
    const { answer, id, categories, ...fieldsToSearch } = standardAnswer;
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
      setPopup({
        message: `Standard answer ${id} deleted`,
        type: "success",
      });
    } else {
      const errorMsg = await response.text();
      setPopup({
        message: `Failed to delete standard answer - ${errorMsg}`,
        type: "error",
      });
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
        <MagnifyingGlass />
        <textarea
          autoFocus
          className="flex-grow ml-2 h-6 bg-transparent outline-none placeholder-subtle overflow-hidden whitespace-normal resize-none"
          role="textarea"
          aria-multiline
          placeholder="Find standard answers by keyword/phrase..."
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
            <div className="my-auto mr-2 w-[16px] h-[16px]">
              <FiTag size={16} />
            </div>
          }
          defaultDisplay="All Categories"
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
      <div className="mx-auto">
        <Table>
          <TableHead>
            <TableRow>
              {columns.map((column) => (
                <TableHeaderCell key={column.key}>
                  {column.name}
                </TableHeaderCell>
              ))}
            </TableRow>
          </TableHead>

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
              <RowTemplate id={0} entries={["", "", "", "", ""]} />
            )}
          </TableBody>
        </Table>
        {paginatedStandardAnswers.length === 0 && (
          <div className="flex justify-center">
            <Text>No matching standard answers found...</Text>
          </div>
        )}
        {paginatedStandardAnswers.length > 0 && (
          <>
            <div className="mt-4">
              <Text>
                Ensure that you have added the category to the relevant{" "}
                <a className="text-link" href="/admin/bot">
                  Slack bot
                </a>
                .
              </Text>
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

const Main = () => {
  const { popup, setPopup } = usePopup();
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
    return <ThreeDotsLoader />;
  }

  if (standardAnswersError || !standardAnswers) {
    return (
      <ErrorCallout
        errorTitle="Error loading standard answers"
        errorMsg={
          standardAnswersError.info?.message ||
          standardAnswersError.message.info?.detail
        }
      />
    );
  }

  if (standardAnswerCategoriesError || !standardAnswerCategories) {
    return (
      <ErrorCallout
        errorTitle="Error loading standard answer categories"
        errorMsg={
          standardAnswerCategoriesError.info?.message ||
          standardAnswerCategoriesError.message.info?.detail
        }
      />
    );
  }

  return (
    <div className="mb-8">
      {popup}

      <Text className="mb-2">
        Manage the standard answers for pre-defined questions.
        <br />
        Note: Currently, only questions asked from Slack can receive standard
        answers.
      </Text>
      {standardAnswers.length == 0 && (
        <Text className="mb-2">Add your first standard answer below!</Text>
      )}
      <div className="mb-2"></div>

      <Link className="flex mb-3 mt-2 w-fit" href="/admin/standard-answer/new">
        <Button className="my-auto" color="green" size="xs">
          New Standard Answer
        </Button>
      </Link>

      <Divider />

      <div>
        <StandardAnswersTable
          standardAnswers={standardAnswers}
          standardAnswerCategories={standardAnswerCategories}
          refresh={refreshStandardAnswers}
          setPopup={setPopup}
        />
      </div>
    </div>
  );
};

const Page = () => {
  return (
    <div className="container mx-auto">
      <AdminPageTitle
        icon={<ClipboardIcon size={32} />}
        title="Standard Answers"
      />
      <Main />
    </div>
  );
};

export default Page;
