import { useState } from "react";
import { useParams } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/components/ui/table";

import { uploadDocument, listDocuments, downloadDocument, deleteDocument, DocumentType, DocumentStatus, DocumentListResponse } from "@/api/documents";
import { useAuth } from "@/context/AuthContext";
import { formatFileSize, formatDate } from "@/lib/utils";

const DOCUMENT_TYPE_LABELS: Record<DocumentType, string> = {
  rfp: "RFP",
  rfq: "RFQ",
  rfi: "RFI",
  knowledge_base: "Knowledge Base",
  other: "Other",
};

const STATUS_COLORS: Record<DocumentStatus, string> = {
  uploaded: "bg-blue-100 text-blue-800",
  processing: "bg-yellow-100 text-yellow-800",
  ready: "bg-green-100 text-green-800",
  failed: "bg-red-100 text-red-800",
};

function DocumentUploadForm({ orgId }: { orgId: string }) {
  const [file, setFile] = useState<File | null>(null);
  const [documentType, setDocumentType] = useState<DocumentType>("other");
  const [isDragging, setIsDragging] = useState(false);
  const queryClient = useQueryClient();
  useAuth();

  const uploadMutation = useMutation({
    mutationFn: () => uploadDocument({ orgId, file: file!, documentType }),
    onSuccess: () => {
      setFile(null);
      setDocumentType("other");
      queryClient.invalidateQueries({ queryKey: ["documents", orgId] });
    },
    onError: (error) => {
      alert(`Upload failed: ${error.message}`);
    },
  });

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  };

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    if (e.dataTransfer.files.length > 0) {
      setFile(e.dataTransfer.files[0]);
    }
  };

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      setFile(e.target.files[0]);
    }
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (file) {
      uploadMutation.mutate();
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Upload Document</CardTitle>
        <CardDescription>Drag and drop a file or click to select</CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div
            className={`border-2 border-dashed rounded-lg p-8 text-center transition-colors ${
              isDragging ? "border-primary bg-primary/5" : "border-slate-300"
            }`}
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
          >
            <input
              type="file"
              id="file-upload"
              onChange={handleFileSelect}
              className="hidden"
              accept=".pdf,.docx,.xlsx,.png,.jpg,.jpeg"
            />
            <label
              htmlFor="file-upload"
              className="cursor-pointer"
            >
              {file ? (
                <div className="flex items-center justify-center space-x-2">
                  <span className="font-medium">{file.name}</span>
                  <span className="text-slate-500">({formatFileSize(file.size)})</span>
                  <Button type="button" variant="ghost" size="sm" onClick={() => setFile(null)}>
                    Remove
                  </Button>
                </div>
              ) : (
                <div className="space-y-2">
                  <p className="text-lg font-medium">Drop files here or click to browse</p>
                  <p className="text-sm text-slate-500">PDF, DOCX, XLSX, PNG, JPG (max 100MB)</p>
                </div>
              )}
            </label>
          </div>

          <div className="grid gap-4 md:grid-cols-2">
            <div>
              <Label htmlFor="document-type">Document Type</Label>
              <Select id="document-type" value={documentType} onChange={(e) => setDocumentType(e.target.value as DocumentType)}>
                <option value="rfp">RFP</option>
                <option value="rfq">RFQ</option>
                <option value="rfi">RFI</option>
                <option value="knowledge_base">Knowledge Base</option>
                <option value="other">Other</option>
              </Select>
            </div>
          </div>

          <Button type="submit" disabled={!file || uploadMutation.isPending} className="w-full">
            {uploadMutation.isPending ? "Uploading..." : "Upload Document"}
          </Button>

          {uploadMutation.isError && (
            <p className="text-red-600 text-sm">Upload failed: {uploadMutation.error?.message}</p>
          )}
        </form>
      </CardContent>
    </Card>
  );
}

function DocumentList({ orgId }: { orgId: string }) {
  const queryClient = useQueryClient();
  const { currentOrg } = useAuth();
  const [filterType, setFilterType] = useState<DocumentType | "all">("all");

  const { data: documents, isLoading, error } = useQuery({
    queryKey: ["documents", orgId, filterType],
    queryFn: () => listDocuments(orgId, filterType === "all" ? undefined : filterType),
  });

  const deleteMutation = useMutation({
    mutationFn: (documentId: string) => deleteDocument(orgId, documentId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["documents", orgId] });
    },
    onError: (error) => {
      alert(`Delete failed: ${error.message}`);
    },
  });

  const handleDownload = async (document: DocumentListResponse) => {
    try {
      const url = await downloadDocument(orgId, document.id);
      window.open(url, "_blank");
    } catch (error) {
      alert(`Download failed: ${error instanceof Error ? error.message : "Unknown error"}`);
    }
  };

  const handleDelete = (document: DocumentListResponse) => {
    if (confirm(`Are you sure you want to delete "${document.filename}"?`)) {
      deleteMutation.mutate(document.id);
    }
  };

  if (isLoading) {
    return (
      <Card>
        <CardContent className="py-12 text-center">
          <p className="text-slate-500">Loading documents...</p>
        </CardContent>
      </Card>
    );
  }

  if (error) {
    return (
      <Card>
        <CardContent className="py-12 text-center">
          <p className="text-red-600">Failed to load documents: {error instanceof Error ? error.message : "Unknown error"}</p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div>
            <CardTitle>Documents</CardTitle>
            <CardDescription>{documents?.length || 0} document(s)</CardDescription>
          </div>
          <Select
            value={filterType}
            onChange={(e) => setFilterType(e.target.value as DocumentType | "all")}
            className="w-[180px]"
          >
            <option value="all">All Types</option>
            <option value="rfp">RFP</option>
            <option value="rfq">RFQ</option>
            <option value="rfi">RFI</option>
            <option value="knowledge_base">Knowledge Base</option>
            <option value="other">Other</option>
          </Select>
        </div>
      </CardHeader>
      <CardContent>
        {documents && documents.length > 0 ? (
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Filename</TableHead>
                  <TableHead>Type</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Size</TableHead>
                  <TableHead>Uploaded</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {documents.map((document) => (
                  <TableRow key={document.id}>
                    <TableCell className="font-medium">{document.filename}</TableCell>
                    <TableCell>
                      <Badge variant="secondary">{DOCUMENT_TYPE_LABELS[document.document_type]}</Badge>
                    </TableCell>
                    <TableCell>
                      <Badge className={STATUS_COLORS[document.status]}>
                        {document.status.charAt(0).toUpperCase() + document.status.slice(1)}
                      </Badge>
                    </TableCell>
                    <TableCell>{formatFileSize(document.size_bytes)}</TableCell>
                    <TableCell>{formatDate(document.created_at)}</TableCell>
                    <TableCell className="text-right">
                      <div className="flex items-center justify-end gap-2">
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => handleDownload(document)}
                        >
                          Download
                        </Button>
                        {(currentOrg?.role === "admin" || currentOrg?.role === "proposal_manager") && (
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => handleDelete(document)}
                            disabled={deleteMutation.isPending}
                            className="text-red-600 hover:bg-red-50"
                          >
                            Delete
                          </Button>
                        )}
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        ) : (
          <div className="py-12 text-center text-slate-500">
            <p>No documents found. Upload your first document above.</p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export function DocumentsPage() {
  const { orgId } = useParams();
  const { currentOrg } = useAuth();

  if (!orgId) {
    return (
      <section className="text-center py-12">
        <p className="text-red-600">Organization ID is required</p>
      </section>
    );
  }

  return (
    <section>
      <div className="mb-6">
        <p className="text-sm font-medium text-slate-500">Organization</p>
        <h1 className="mt-2 text-3xl font-semibold tracking-tight">{currentOrg?.org_name || orgId}</h1>
      </div>

      <div className="space-y-6">
        <DocumentUploadForm orgId={orgId} />
        <DocumentList orgId={orgId} />
      </div>
    </section>
  );
}