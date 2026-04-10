"use client";

import { useParams } from "next/navigation";
import ProposalReview from "@/app/proposal-review/components/ProposalReview";

/**
 * Proposal Review Detail Page
 *
 * Three-panel layout for reviewing a single proposal:
 * - Left: Proposal info + documents
 * - Center: AI review checklist with findings
 * - Right: Summary counts + decision panel
 */
export default function ProposalReviewDetailPage() {
  const params = useParams<{ id: string }>();
  const proposalId = params.id;

  return <ProposalReview proposalId={proposalId} />;
}
