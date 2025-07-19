import {
  AgentAnswerPiece,
  SubQuestionPiece,
  SubQuestionSearchDoc,
} from "@/lib/search/interfaces";
import { StreamStopInfo } from "@/lib/search/interfaces";
import { SubQueryPiece } from "@/lib/search/interfaces";
import { SubQuestionDetail } from "../interfaces";

import { DocumentsResponse } from "../interfaces";

export const constructSubQuestions = (
  subQuestions: SubQuestionDetail[],
  newDetail:
    | SubQuestionPiece
    | SubQueryPiece
    | AgentAnswerPiece
    | SubQuestionSearchDoc
    | DocumentsResponse
    | StreamStopInfo
): SubQuestionDetail[] => {
  if (!newDetail) {
    return subQuestions;
  }
  if (newDetail.level_question_num == 0) {
    return subQuestions;
  }

  const updatedSubQuestions = [...subQuestions];

  if ("stop_reason" in newDetail) {
    const { level, level_question_num } = newDetail;
    let subQuestion = updatedSubQuestions.find(
      (sq) => sq.level === level && sq.level_question_num === level_question_num
    );
    if (subQuestion) {
      if (newDetail.stream_type == "sub_answer") {
        subQuestion.answer_streaming = false;
      } else {
        subQuestion.is_complete = true;
        subQuestion.is_stopped = true;
      }
    }
  } else if ("top_documents" in newDetail) {
    const { level, level_question_num, top_documents } = newDetail;
    let subQuestion = updatedSubQuestions.find(
      (sq) => sq.level === level && sq.level_question_num === level_question_num
    );
    if (!subQuestion) {
      subQuestion = {
        level: level ?? 0,
        level_question_num: level_question_num ?? 0,
        question: "",
        answer: "",
        sub_queries: [],
        context_docs: { top_documents },
        is_complete: false,
      };
    } else {
      subQuestion.context_docs = { top_documents };
    }
  } else if ("answer_piece" in newDetail) {
    // Handle AgentAnswerPiece
    const { level, level_question_num, answer_piece } = newDetail;
    // Find or create the relevant SubQuestionDetail
    let subQuestion = updatedSubQuestions.find(
      (sq) => sq.level === level && sq.level_question_num === level_question_num
    );

    if (!subQuestion) {
      subQuestion = {
        level,
        level_question_num,
        question: "",
        answer: "",
        sub_queries: [],
        context_docs: undefined,
        is_complete: false,
      };
      updatedSubQuestions.push(subQuestion);
    }

    // Append to the answer
    subQuestion.answer += answer_piece;
  } else if ("sub_question" in newDetail) {
    // Handle SubQuestionPiece
    const { level, level_question_num, sub_question } = newDetail;

    // Find or create the relevant SubQuestionDetail
    let subQuestion = updatedSubQuestions.find(
      (sq) => sq.level === level && sq.level_question_num === level_question_num
    );

    if (!subQuestion) {
      subQuestion = {
        level,
        level_question_num,
        question: "",
        answer: "",
        sub_queries: [],
        context_docs: undefined,
        is_complete: false,
      };
      updatedSubQuestions.push(subQuestion);
    }

    // Append to the question
    subQuestion.question += sub_question;
  } else if ("sub_query" in newDetail) {
    // Handle SubQueryPiece
    const { level, level_question_num, query_id, sub_query } = newDetail;

    // Find the relevant SubQuestionDetail
    let subQuestion = updatedSubQuestions.find(
      (sq) => sq.level === level && sq.level_question_num === level_question_num
    );

    if (!subQuestion) {
      // If we receive a sub_query before its parent question, create a placeholder
      subQuestion = {
        level,
        level_question_num: level_question_num,
        question: "",
        answer: "",
        sub_queries: [],
        context_docs: undefined,
      };
      updatedSubQuestions.push(subQuestion);
    }

    // Find or create the relevant SubQueryDetail
    let subQuery = subQuestion.sub_queries?.find(
      (sq) => sq.query_id === query_id
    );

    if (!subQuery) {
      subQuery = { query: "", query_id };
      subQuestion.sub_queries = [...(subQuestion.sub_queries || []), subQuery];
    }

    // Append to the query
    subQuery.query += sub_query;
  }

  return updatedSubQuestions;
};
