import { apiClient } from "@/api/client";

export interface SearchFilter {
  document_id?: string;
  document_type?: string;
  date_from?: string;
  date_to?: string;
}

export interface SearchRequest {
  query: string;
  filters?: SearchFilter;
  top_k?: number;
}

export interface SearchResult {
  chunk_id: string;
  document_id: string;
  content: string;
  chunk_type: string;
  page_start: number;
  page_end: number;
  section_path?: string;
  token_count: number;
  filename: string;
  document_type: string;
  rrf_score: number;
  vector_rank?: number;
  fulltext_rank?: number;
}

export interface SearchResponse {
  results: SearchResult[];
  total_results: number;
  query: string;
}

export async function searchDocuments(
  orgId: string,
  request: SearchRequest
): Promise<SearchResponse> {
  return apiClient.post<SearchResponse>(`/orgs/${orgId}/search`, {
    body: JSON.stringify(request),
    headers: {
      "Content-Type": "application/json",
    },
  });
}