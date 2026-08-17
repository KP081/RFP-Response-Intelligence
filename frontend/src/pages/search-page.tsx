import { useState } from "react";
import { useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Label } from "@/components/ui/label";

import { searchDocuments, SearchRequest, SearchFilter, SearchResult, SearchResponse } from "@/api/search";
import { useAuth } from "@/context/AuthContext";
import { formatDate } from "@/lib/utils";

const CHUNK_TYPE_LABELS: Record<string, string> = {
  text: "Text",
  table: "Table",
  heading: "Heading",
};

const CHUNK_TYPE_COLORS: Record<string, string> = {
  text: "bg-blue-100 text-blue-800",
  table: "bg-green-100 text-green-800",
  heading: "bg-purple-100 text-purple-800",
};

function SearchForm({ orgId, onSearch }: { orgId: string; onSearch: (request: SearchRequest) => void }) {
  const [query, setQuery] = useState("");
  const [documentId, setDocumentId] = useState("");
  const [documentType, setDocumentType] = useState("");
  const [topK, setTopK] = useState(10);
  const [isSearching, setIsSearching] = useState(false);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!query.trim()) return;

    const filters: SearchFilter = {};
    if (documentId) filters.document_id = documentId;
    if (documentType) filters.document_type = documentType;

    const request: SearchRequest = {
      query: query.trim(),
      filters,
      top_k: topK,
    };

    onSearch(request);
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Search Documents</CardTitle>
        <CardDescription>Semantic + keyword hybrid search across all document chunks</CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <Label htmlFor="search-query">Search Query</Label>
            <Input
              id="search-query"
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="e.g., liquidated damages, Application Architect hourly rate..."
              className="mt-1"
              disabled={isSearching}
            />
          </div>

          <div className="grid gap-4 md:grid-cols-3">
            <div>
              <Label htmlFor="search-document-id">Document ID (optional)</Label>
              <Input
                id="search-document-id"
                type="text"
                value={documentId}
                onChange={(e) => setDocumentId(e.target.value)}
                placeholder="Filter by document UUID"
                className="mt-1"
                disabled={isSearching}
              />
            </div>
            <div>
              <Label htmlFor="search-document-type">Document Type (optional)</Label>
              <Select
                id="search-document-type"
                value={documentType}
                onChange={(e) => setDocumentType(e.target.value)}
                className="mt-1"
                disabled={isSearching}
              >
                <option value="">All Types</option>
                <option value="rfp">RFP</option>
                <option value="rfq">RFQ</option>
                <option value="rfi">RFI</option>
                <option value="knowledge_base">Knowledge Base</option>
                <option value="other">Other</option>
              </Select>
            </div>
            <div>
              <Label htmlFor="search-top-k">Results</Label>
              <Select
                id="search-top-k"
                value={topK}
                onChange={(e) => setTopK(Number(e.target.value))}
                className="mt-1"
                disabled={isSearching}
              >
                <option value="5">5</option>
                <option value="10">10</option>
                <option value="20">20</option>
                <option value="50">50</option>
              </Select>
            </div>
          </div>

          <Button type="submit" disabled={!query.trim() || isSearching} className="w-full md:w-auto">
            {isSearching ? "Searching..." : "Search"}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}

function SearchResults({ results, query }: { results: SearchResult[]; query: string }) {
  if (results.length === 0) {
    return (
      <Card>
        <CardContent className="py-12 text-center text-slate-500">
          <p>No results found for "{query}"</p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Search Results</CardTitle>
        <CardDescription>{results.length} result(s) for "{query}"</CardDescription>
      </CardHeader>
      <CardContent>
        <div className="space-y-4">
          {results.map((result, index) => (
            <div
              key={result.chunk_id}
              className="border rounded-lg p-4 hover:bg-slate-50 transition-colors"
            >
              <div className="flex items-start justify-between gap-4 mb-2">
                <div className="flex items-center gap-2">
                  <span className="font-mono text-sm text-slate-500">#{index + 1}</span>
                  <Badge className={CHUNK_TYPE_COLORS[result.chunk_type] || "bg-slate-100 text-slate-800"}>
                    {CHUNK_TYPE_LABELS[result.chunk_type] || result.chunk_type}
                  </Badge>
                  <Badge variant="secondary">{result.document_type.toUpperCase()}</Badge>
                </div>
                <div className="flex items-center gap-2 text-sm text-slate-500">
                  <span>Score: {result.rrf_score.toFixed(4)}</span>
                  {result.vector_rank && <span>Vec: #{result.vector_rank}</span>}
                  {result.fulltext_rank && <span>FT: #{result.fulltext_rank}</span>}
                </div>
              </div>

              <div className="text-sm text-slate-600 mb-2">
                <span className="font-medium">{result.filename}</span>
                {result.section_path && (
                  <span className="ml-2 text-slate-500">› {result.section_path}</span>
                )}
                <span className="ml-2 text-slate-400">pp. {result.page_start}–{result.page_end}</span>
              </div>

              <div className="bg-slate-50 rounded p-3 text-sm font-mono text-slate-700 max-h-40 overflow-auto">
                {result.content.slice(0, 500)}{result.content.length > 500 ? "..." : ""}
              </div>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

export function SearchPage() {
  const { orgId } = useParams();
  const { currentOrg } = useAuth();
  const [searchRequest, setSearchRequest] = useState<SearchRequest | null>(null);
  const [lastQuery, setLastQuery] = useState("");

  if (!orgId) {
    return (
      <section className="text-center py-12">
        <p className="text-red-600">Organization ID is required</p>
      </section>
    );
  }

  const { data: searchResults, isLoading, error } = useQuery<SearchResponse>({
    queryKey: ["search", orgId, searchRequest],
    queryFn: () => searchDocuments(orgId, searchRequest!),
    enabled: !!searchRequest,
  });

  const handleSearch = (request: SearchRequest) => {
    setSearchRequest(request);
    setLastQuery(request.query);
  };

  return (
    <section>
      <div className="mb-6">
        <p className="text-sm font-medium text-slate-500">Organization</p>
        <h1 className="mt-2 text-3xl font-semibold tracking-tight">{currentOrg?.org_name || orgId}</h1>
      </div>

      <div className="space-y-6">
        <SearchForm orgId={orgId} onSearch={handleSearch} />

        {isLoading && (
          <Card>
            <CardContent className="py-12 text-center">
              <p className="text-slate-500">Searching...</p>
            </CardContent>
          </Card>
        )}

        {error && (
          <Card>
            <CardContent className="py-12 text-center">
              <p className="text-red-600">Search failed: {error instanceof Error ? error.message : "Unknown error"}</p>
            </CardContent>
          </Card>
        )}

        {searchResults && !isLoading && (
          <SearchResults results={searchResults.results} query={lastQuery} />
        )}
      </div>
    </section>
  );
}