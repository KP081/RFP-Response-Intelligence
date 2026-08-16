import { useState } from "react";
import { useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Label } from "@/components/ui/label";
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
} from "@/components/ui/card";
import {
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { useAuth } from "@/context/AuthContext";
import { format } from "date-fns";

interface AuditLogEntry {
  id: string;
  org_id: string;
  actor_user_id: string | null;
  action: string;
  resource_type: string;
  resource_id: string;
  event_metadata: Record<string, unknown>;
  correlation_id: string;
  created_at: string;
}

interface AuditLogListResponse {
  items: AuditLogEntry[];
  total: number;
  page: number;
  page_size: number;
}

const ACTIONS = [
  "document.upload",
  "document.download",
  "document.delete",
] as const;

const RESOURCE_TYPES = [
  "document",
] as const;

export function AuditLogPage() {
  const { orgId } = useParams<{ orgId: string }>();
  const { currentOrg, memberships } = useAuth();

  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const [actionFilter, setActionFilter] = useState("");
  const [resourceTypeFilter, setResourceTypeFilter] = useState("");
  const [actorFilter, setActorFilter] = useState("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");

  const currentUserMembership = memberships.find((m) => m.org_id === orgId);
  const isAuthorized =
    currentUserMembership &&
    ["admin", "security", "compliance"].includes(currentUserMembership.role);

  const buildQueryParams = () => {
    const params = new URLSearchParams();
    params.append("page", page.toString());
    params.append("page_size", pageSize.toString());
    if (actionFilter) params.append("action", actionFilter);
    if (resourceTypeFilter) params.append("resource_type", resourceTypeFilter);
    if (actorFilter) params.append("actor_user_id", actorFilter);
    if (startDate) params.append("start_date", startDate);
    if (endDate) params.append("end_date", endDate);
    return params.toString();
  };

  const { data: auditLog, isLoading, error } = useQuery({
    queryKey: ["audit-log", orgId, buildQueryParams()],
    queryFn: async () => {
      const response = await apiClient.get<AuditLogListResponse>(
        `/orgs/${orgId}/audit-log?${buildQueryParams()}`
      );
      return response;
    },
    enabled: !!orgId && isAuthorized,
  });

  const handleFilterChange = () => {
    setPage(1);
  };

  const handlePageChange = (newPage: number) => {
    setPage(newPage);
  };

  const handlePageSizeChange = (newSize: number) => {
    setPageSize(newSize);
    setPage(1);
  };

  if (!orgId) {
    return <div>Loading...</div>;
  }

  if (!isAuthorized) {
    return (
      <section>
        <div className="mb-6">
          <p className="text-sm font-medium text-slate-500">Audit Log</p>
          <h1 className="mt-2 text-3xl font-semibold tracking-tight">
            {currentOrg?.org_name}
          </h1>
        </div>
        <Card>
          <CardContent className="py-12 text-center">
            <p className="text-slate-500">
              You do not have permission to view the audit log.
              This page is restricted to admin, security, and compliance roles.
            </p>
          </CardContent>
        </Card>
      </section>
    );
  }

  return (
    <section>
      <div className="mb-6">
        <p className="text-sm font-medium text-slate-500">Audit Log</p>
        <h1 className="mt-2 text-3xl font-semibold tracking-tight">
          {currentOrg?.org_name}
        </h1>
      </div>

      {/* Filters */}
      <Card className="mb-6">
        <CardHeader>
          <CardTitle>Filters</CardTitle>
          <CardDescription>
            Filter audit log entries by action, resource type, actor, and date range.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-6">
            <div className="grid gap-2">
              <Label htmlFor="action">Action</Label>
              <Select
                id="action"
                value={actionFilter}
                onChange={(e) => {
                  setActionFilter(e.target.value);
                  handleFilterChange();
                }}
              >
                <option value="">All Actions</option>
                {ACTIONS.map((action) => (
                  <option key={action} value={action}>
                    {action}
                  </option>
                ))}
              </Select>
            </div>
            <div className="grid gap-2">
              <Label htmlFor="resourceType">Resource Type</Label>
              <Select
                id="resourceType"
                value={resourceTypeFilter}
                onChange={(e) => {
                  setResourceTypeFilter(e.target.value);
                  handleFilterChange();
                }}
              >
                <option value="">All Types</option>
                {RESOURCE_TYPES.map((type) => (
                  <option key={type} value={type}>
                    {type}
                  </option>
                ))}
              </Select>
            </div>
            <div className="grid gap-2">
              <Label htmlFor="actor">Actor User ID</Label>
              <Input
                id="actor"
                type="text"
                placeholder="User UUID"
                value={actorFilter}
                onChange={(e) => {
                  setActorFilter(e.target.value);
                  handleFilterChange();
                }}
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="startDate">Start Date</Label>
              <Input
                id="startDate"
                type="date"
                value={startDate}
                onChange={(e) => {
                  setStartDate(e.target.value);
                  handleFilterChange();
                }}
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="endDate">End Date</Label>
              <Input
                id="endDate"
                type="date"
                value={endDate}
                onChange={(e) => {
                  setEndDate(e.target.value);
                  handleFilterChange();
                }}
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="pageSize">Page Size</Label>
              <Select
                id="pageSize"
                value={pageSize.toString()}
                onChange={(e) => handlePageSizeChange(Number(e.target.value))}
              >
                <option value="10">10</option>
                <option value="25">25</option>
                <option value="50">50</option>
                <option value="100">100</option>
              </Select>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Audit Log Table */}
      <Card>
        <CardHeader>
          <CardTitle>Audit Log Entries</CardTitle>
          <CardDescription>
            Showing {auditLog?.items.length || 0} of {auditLog?.total || 0} entries
          </CardDescription>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <p className="text-slate-500">Loading audit log...</p>
          ) : error ? (
            <p className="text-red-600">Failed to load audit log: {String(error)}</p>
          ) : (
            <>
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Timestamp</TableHead>
                      <TableHead>Action</TableHead>
                      <TableHead>Resource</TableHead>
                      <TableHead>Actor</TableHead>
                      <TableHead>Correlation ID</TableHead>
                      <TableHead>Details</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {auditLog?.items.map((entry) => (
                      <TableRow key={entry.id}>
                        <TableCell>
                          {format(new Date(entry.created_at), "yyyy-MM-dd HH:mm:ss")}
                        </TableCell>
                        <TableCell>
                          <Badge variant="secondary">{entry.action}</Badge>
                        </TableCell>
                        <TableCell>
                          {entry.resource_type} ({entry.resource_id.slice(0, 8)}...)
                        </TableCell>
                        <TableCell>
                          {entry.actor_user_id || "System"}
                        </TableCell>
                        <TableCell>
                          <code className="text-xs text-slate-500">
                            {entry.correlation_id.slice(0, 8)}...
                          </code>
                        </TableCell>
                        <TableCell>
                          <pre className="text-xs text-slate-500 max-h-24 overflow-auto">
                            {JSON.stringify(entry.event_metadata, null, 2)}
                          </pre>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
              {!auditLog?.items.length && (
                <p className="text-center text-slate-500 py-8">No audit log entries found.</p>
              )}

              {/* Pagination */}
              {auditLog && auditLog.total > pageSize && (
                <div className="mt-4 flex items-center justify-between">
                  <p className="text-sm text-slate-500">
                    Page {auditLog.page} of {Math.ceil(auditLog.total / auditLog.page_size)}
                  </p>
                  <div className="flex items-center gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => handlePageChange(auditLog.page - 1)}
                      disabled={auditLog.page === 1}
                    >
                      Previous
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => handlePageChange(auditLog.page + 1)}
                      disabled={auditLog.page >= Math.ceil(auditLog.total / auditLog.page_size)}
                    >
                      Next
                    </Button>
                  </div>
                </div>
              )}
            </>
          )}
        </CardContent>
      </Card>
    </section>
  );
}