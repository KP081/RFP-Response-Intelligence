import { apiClient } from "@/api/client";

export type DocumentType = "rfp" | "rfq" | "rfi" | "knowledge_base" | "other";
export type DocumentStatus = "uploaded" | "processing" | "ready" | "failed";

export type PipelineStage = "extract" | "chunk" | "embed" | "ocr" | "caption_figures" | "dedupe";
export type PipelineStageStatus = "queued" | "running" | "succeeded" | "failed" | "skipped";

export interface PipelineStageStatusInfo {
  status: PipelineStageStatus;
  complete: boolean;
}

export interface PipelineStatusResponse {
  document_id: string;
  status: DocumentStatus;
  current_stage: PipelineStage | "completed" | null;
  pipeline_stage_status: PipelineStageStatus;
  stages: Record<PipelineStage, PipelineStageStatusInfo>;
}

export interface DocumentResponse {
  id: string;
  org_id: string;
  uploaded_by_user_id: string;
  filename: string;
  mime_type: string;
  document_type: DocumentType;
  status: DocumentStatus;
  storage_key: string;
  size_bytes: number;
  created_at: string;
}

export type DocumentUploadResponse = DocumentResponse;
export type DocumentListResponse = DocumentResponse;
export type DocumentDetailResponse = DocumentResponse;

export interface DocumentDeleteResponse {
  message: string;
}

export interface UploadDocumentParams {
  orgId: string;
  file: File;
  documentType?: DocumentType;
}

export async function uploadDocument({
  orgId,
  file,
  documentType = "other",
}: UploadDocumentParams): Promise<DocumentUploadResponse> {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("document_type", documentType);

  const response = await apiClient.post<DocumentUploadResponse>(
    `/orgs/${orgId}/documents`,
    {
      body: formData,
      headers: {
        // Don't set Content-Type - let the browser set it with the boundary
      },
    }
  );
  return response;
}

export async function listDocuments(
  orgId: string,
  documentType?: DocumentType
): Promise<DocumentListResponse[]> {
  const params = new URLSearchParams();
  if (documentType) {
    params.append("document_type", documentType);
  }
  const queryString = params.toString();
  const path = `/orgs/${orgId}/documents${queryString ? `?${queryString}` : ""}`;
  return apiClient.get<DocumentListResponse[]>(path);
}

export async function getDocument(orgId: string, documentId: string): Promise<DocumentDetailResponse> {
  return apiClient.get<DocumentDetailResponse>(`/orgs/${orgId}/documents/${documentId}`);
}

export async function downloadDocument(orgId: string, documentId: string): Promise<string> {
  // This will follow the redirect to the presigned URL
  const response = await fetch(
    `${import.meta.env.VITE_API_BASE_URL}/orgs/${orgId}/documents/${documentId}/download`,
    {
      credentials: "include",
      redirect: "manual", // Don't follow redirect automatically
    }
  );

  if (response.status === 302 || response.status === 301) {
    const redirectUrl = response.headers.get("Location");
    if (redirectUrl) {
      return redirectUrl;
    }
  }

  // If not a redirect, try to get the URL from response
  const data = await response.json().catch(() => null);
  if (data?.url) {
    return data.url;
  }

  throw new Error("Failed to get download URL");
}

export async function deleteDocument(orgId: string, documentId: string): Promise<DocumentDeleteResponse> {
  return apiClient.delete<DocumentDeleteResponse>(`/orgs/${orgId}/documents/${documentId}`);
}

export async function getPipelineStatus(
  orgId: string,
  documentId: string
): Promise<PipelineStatusResponse> {
  return apiClient.get<PipelineStatusResponse>(`/orgs/${orgId}/documents/${documentId}/pipeline-status`);
}

export async function retryPipeline(
  orgId: string,
  documentId: string
): Promise<{ status: string; correlation_id: string }> {
  return apiClient.post<{ status: string; correlation_id: string }>(
    `/orgs/${orgId}/documents/${documentId}/pipeline-retry`,
    {}
  );
}

export function createPipelineEventStream(
  orgId: string,
  documentId: string,
  onMessage: (data: PipelineStatusResponse) => void,
  onError?: (error: Error) => void
): EventSource {
  const url = `${import.meta.env.VITE_API_BASE_URL}/orgs/${orgId}/documents/${documentId}/pipeline-events`;
  const eventSource = new EventSource(url, { withCredentials: true });

  eventSource.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data) as PipelineStatusResponse;
      onMessage(data);
    } catch (e) {
      console.error("Failed to parse pipeline event:", e);
    }
  };

  eventSource.onerror = (error) => {
    if (onError) {
      onError(new Error("SSE connection error"));
    }
    // EventSource automatically reconnects
  };

  return eventSource;
}