import { StandaloneKnowledgeEvidence } from "@/components/knowledge/citation-viewer";

export default async function EvidencePage({ params }: { params: Promise<{ searchId: string; citationId: string }> }) {
  const { searchId, citationId } = await params;
  return <StandaloneKnowledgeEvidence searchId={searchId} citationId={citationId} />;
}
