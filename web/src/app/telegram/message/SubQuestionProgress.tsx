import i18n from "@/i18n/init";
import k from "./../../../i18n/keys";
import React from "react";
import { SubQuestionDetail } from "../interfaces";
import { OnyxDocument } from "@/lib/search/interfaces";

import {
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableRow,
} from "@/components/ui/table";

import {
  Popover,
  PopoverTrigger,
  PopoverContent,
} from "@/components/ui/popover";

interface SubQuestionProgressProps {
  subQuestions: SubQuestionDetail[];
}

const SubQuestionProgress: React.FC<SubQuestionProgressProps> = ({
  subQuestions,
}) => {
  return (
    <div className="sub-question-progress space-y-4">
      <Table>
        <TableBody>
          {subQuestions.map((sq, index) => (
            <TableRow key={index}>
              <TableCell>
                {i18n.t(k.LEVEL)} {sq.level}
                {i18n.t(k.Q)}
                {sq.level_question_num}
              </TableCell>
              <TableCell>
                <Popover>
                  <PopoverTrigger>
                    {sq.question
                      ? i18n.t(k.GENERATED)
                      : i18n.t(k.NOT_GENERATED)}
                  </PopoverTrigger>
                  <PopoverContent>
                    <p>{sq.question || "Question not generated yet"}</p>
                  </PopoverContent>
                </Popover>
              </TableCell>
              <TableCell>
                <Popover>
                  <PopoverTrigger>
                    {sq.answer ? i18n.t(k.ANSWERED) : i18n.t(k.NOT_ANSWERED)}
                  </PopoverTrigger>
                  <PopoverContent>
                    <p>{sq.answer || "Answer not available yet"}</p>
                  </PopoverContent>
                </Popover>
              </TableCell>
              <TableCell>
                <Popover>
                  <PopoverTrigger>
                    {sq.sub_queries
                      ? `${sq.sub_queries.length} ${i18n.t(k.SUB_QUERIES)}`
                      : i18n.t(k.NO_SUB_QUERIES)}
                  </PopoverTrigger>
                  <PopoverContent>
                    <ul>
                      {sq.sub_queries?.map((query, i) => (
                        <li key={i}>{query.query}</li>
                      ))}
                    </ul>
                  </PopoverContent>
                </Popover>
              </TableCell>
              <TableCell>
                <Popover>
                  <PopoverTrigger>
                    {sq.context_docs
                      ? `${sq.context_docs.top_documents.length} ${i18n.t(
                          k.DOCS
                        )}`
                      : i18n.t(k.NO_DOCS)}
                  </PopoverTrigger>
                  <PopoverContent>
                    <ul>
                      {sq.context_docs?.top_documents.map((doc, i) => (
                        <li key={i}>{doc.semantic_identifier}</li>
                      ))}
                    </ul>
                  </PopoverContent>
                </Popover>
              </TableCell>
              <TableCell>
                {sq.is_complete ? i18n.t(k.COMPLETE) : i18n.t(k.GENERATING)}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
};

export default SubQuestionProgress;
