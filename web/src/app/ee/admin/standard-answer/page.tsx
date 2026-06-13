"use client";

import { SettingsLayouts } from "@opal/layouts";
import { toast } from "@/hooks/useToast";
import { useStandardAnswers, useStandardAnswerCategories } from "./hooks";
import { ThreeDotsLoader } from "@/components/Loading";
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
import { MagnifyingGlass } from "@phosphor-icons/react";
import { useState, JSX } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { deleteStandardAnswer } from "./lib";
import { FilterDropdown } from "@/components/search/filtering/FilterDropdown";
import { FiTag } from "react-icons/fi";
import { PageSelector } from "@/components/PageSelector";
import { Text } from "@opal/components";
import { markdown } from "@opal/utils";
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
      bg-accent-background-hovered
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
        aria-label="移除分类"
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
            <span className="text-green-500 font-medium">是</span>
          ) : (
            <span className="text-gray-500">否</span>
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
  const [query, setQuery] = useState("");
  const [currentPage, setCurrentPage] = useState(1);
  const [selectedCategories, setSelectedCategories] = useState<
    StandardAnswerCategory[]
  >([]);
  const columns = [
    { name: "", key: "edit" },
    { name: "分类", key: "category" },
    { name: "关键词/模式", key: "keyword" },
    { name: "匹配 Regex？", key: "match_regex" },
    { name: "答案", key: "answer" },
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
      toast.success(`标准答案 ${id} 已删除`);
    } else {
      const errorMsg = await response.text();
      toast.error(`删除标准答案失败 - ${errorMsg}`);
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
          className="grow ml-2 h-6 bg-transparent outline-hidden placeholder-subtle overflow-hidden whitespace-normal resize-none"
          role="textarea"
          aria-multiline
          placeholder="按关键词/短语查找标准答案..."
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
          defaultDisplay="全部分类"
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
              <Text as="p">未找到匹配的标准答案...</Text>
            </div>
          )}
        </div>
        {paginatedStandardAnswers.length > 0 && (
          <>
            <div className="mt-4">
              <Text as="p">
                {markdown(
                  "请确保已将该分类添加到相关的 [Slack Bot](/admin/bots)。"
                )}
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

function Main() {
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
        errorTitle="加载标准答案失败"
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
        errorTitle="加载标准答案分类失败"
        errorMsg={
          standardAnswerCategoriesError.info?.detail ||
          standardAnswerCategoriesError.info?.message
        }
      />
    );
  }

  return (
    <div className="mb-8">
      <Text as="p">
        {markdown(
          "管理预定义问题的标准答案。\n注意：目前只有来自 Slack 的问题可以收到标准答案。"
        )}
      </Text>
      <Spacer rem={0.5} />
      {standardAnswers.length == 0 && (
        <>
          <Text as="p">在下方添加你的第一个标准答案！</Text>
          <Spacer rem={0.5} />
        </>
      )}
      <div className="mb-2"></div>

      <Button
        icon={SvgPlusCircle}
        prominence="secondary"
        href="/admin/standard-answer/new"
      >
        新建标准答案
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
  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header icon={route.icon} title={route.title} divider />
      <SettingsLayouts.Body>
        <Main />
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
