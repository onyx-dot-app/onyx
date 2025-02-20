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
                Level {sq.level}, Q{sq.level_question_num}
              </TableCell>
              <TableCell>
                <Popover>
                  <PopoverTrigger>
                    {sq.question ? "Generated" : "Not generated"}
                  </PopoverTrigger>
                  <PopoverContent>
                    <p>{sq.question || "Question not generated yet"}</p>
                  </PopoverContent>
                </Popover>
              </TableCell>
              <TableCell>
                <Popover>
                  <PopoverTrigger>
                    {sq.answer ? "Answered" : "Not answered"}
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
                      ? `${sq.sub_queries.length} sub-queries`
                      : "No sub-queries"}
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
                      ? `${sq.context_docs.top_documents.length} docs`
                      : "No docs"}
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
                {sq.is_complete ? "Complete" : "Generating..."}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
};

export default SubQuestionProgress;
