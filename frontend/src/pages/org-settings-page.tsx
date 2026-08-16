import { useState } from "react";
import { useParams } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";

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
import { Badge, getRoleBadgeVariant, getRoleDisplayName } from "@/components/ui/badge";
import {
  Dialog,
  DialogTrigger,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
  DialogCloseButton,
} from "@/components/ui/dialog";
import { useAuth } from "@/context/AuthContext";

interface OrgMember {
  user_id: string;
  display_name: string;
  email: string;
  role: string;
  joined_at: string;
}

interface OrgInvite {
  id: string;
  org_id: string;
  email: string;
  role: string;
  token: string;
  invited_by_user_id: string;
  status: string;
  created_at: string;
  expires_at: string;
  invite_link: string;
}

interface InviteCreate {
  email: string;
  role: string;
}

const ROLES = [
  "admin",
  "proposal_manager",
  "sales",
  "presales_architect",
  "legal",
  "security",
  "compliance",
  "viewer",
] as const;

export function OrgSettingsPage() {
  const { orgId } = useParams<{ orgId: string }>();
  const { currentOrg, memberships } = useAuth();
  const queryClient = useQueryClient();

  const [showInviteDialog, setShowInviteDialog] = useState(false);
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState("viewer");
  const [copiedLink, setCopiedLink] = useState<string | null>(null);
  const [editingMemberId, setEditingMemberId] = useState<string | null>(null);
  const [editRole, setEditRole] = useState("viewer");

  // Fetch org members
  const { data: members, isLoading: membersLoading } = useQuery({
    queryKey: ["org-members", orgId],
    queryFn: async () => {
      const response = await apiClient.get<OrgMember[]>(`/orgs/${orgId}/members`);
      return response;
    },
    enabled: !!orgId,
  });

  // Create invite mutation
  const createInviteMutation = useMutation({
    mutationFn: async (data: InviteCreate) => {
      const response = await apiClient.post<OrgInvite>(`/orgs/${orgId}/invites`, {
        body: JSON.stringify(data),
      });
      return response;
    },
    onSuccess: (invite) => {
      queryClient.invalidateQueries({ queryKey: ["org-members", orgId] });
      setCopiedLink(invite.invite_link);
      setInviteEmail("");
      setInviteRole("viewer");
      setShowInviteDialog(false);
    },
  });

  // Update member role mutation
  const updateMemberMutation = useMutation({
    mutationFn: async ({ userId, role }: { userId: string; role: string }) => {
      const response = await apiClient.request<OrgMember>(`/orgs/${orgId}/members/${userId}`, {
        method: "PATCH",
        body: JSON.stringify({ role }),
      });
      return response;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["org-members", orgId] });
      setEditingMemberId(null);
    },
  });

  // Remove member mutation
  const removeMemberMutation = useMutation({
    mutationFn: async (userId: string) => {
      await apiClient.request(`/orgs/${orgId}/members/${userId}`, { method: "DELETE" });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["org-members", orgId] });
    },
  });

  const currentUserMembership = memberships.find((m) => m.org_id === orgId);
  const isAdmin = currentUserMembership?.role === "admin";

  const handleInviteSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    createInviteMutation.mutate({ email: inviteEmail, role: inviteRole });
  };

  const handleRoleChange = (userId: string, role: string) => {
    updateMemberMutation.mutate({ userId, role });
  };

  const handleRemoveMember = (userId: string) => {
    if (window.confirm("Are you sure you want to remove this member?")) {
      removeMemberMutation.mutate(userId);
    }
  };

  const copyInviteLink = (link: string) => {
    navigator.clipboard.writeText(link);
    setCopiedLink(link);
    setTimeout(() => setCopiedLink(null), 2000);
  };

  if (!orgId) {
    return <div>Loading...</div>;
  }

  return (
    <section>
      <div className="mb-6">
        <p className="text-sm font-medium text-slate-500">Organization Settings</p>
        <h1 className="mt-2 text-3xl font-semibold tracking-tight">{currentOrg?.org_name}</h1>
      </div>

      <div className="grid gap-6 md:grid-cols-2">
        {/* Members Section */}
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 p-6">
            <div>
              <CardTitle>Members</CardTitle>
              <CardDescription>Manage organization members and their roles</CardDescription>
            </div>
            {isAdmin && (
              <Dialog open={showInviteDialog} onOpenChange={setShowInviteDialog}>
                <DialogTrigger asChild>
                  <Button>Invite User</Button>
                </DialogTrigger>
                <DialogContent>
                  <DialogCloseButton />
                  <DialogHeader>
                    <DialogTitle>Invite New Member</DialogTitle>
                    <DialogDescription>
                      Enter the email address and role for the new member. An invite link will be generated.
                    </DialogDescription>
                  </DialogHeader>
                  <form onSubmit={handleInviteSubmit}>
                    <div className="grid gap-4 py-4">
                      <div className="grid gap-2">
                        <Label htmlFor="email">Email</Label>
                        <Input
                          id="email"
                          type="email"
                          placeholder="user@example.com"
                          value={inviteEmail}
                          onChange={(e) => setInviteEmail(e.target.value)}
                          required
                        />
                      </div>
                      <div className="grid gap-2">
                        <Label htmlFor="role">Role</Label>
                        <Select
                          id="role"
                          value={inviteRole}
                          onChange={(e) => setInviteRole(e.target.value)}
                        >
                          {ROLES.map((role) => (
                            <option key={role} value={role}>
                              {getRoleDisplayName(role)}
                            </option>
                          ))}
                        </Select>
                      </div>
                      {copiedLink && (
                        <div className="grid gap-2">
                          <Label>Invite Link (Copied!)</Label>
                          <div className="flex items-center gap-2">
                            <Input
                              value={copiedLink}
                              readOnly
                              className="flex-1 bg-slate-50"
                            />
                            <Button
                              type="button"
                              variant="outline"
                              size="sm"
                              onClick={() => copyInviteLink(copiedLink)}
                            >
                              Copy
                            </Button>
                          </div>
                        </div>
                      )}
                    </div>
                    <DialogFooter>
                      <Button type="submit" disabled={createInviteMutation.isPending}>
                        {createInviteMutation.isPending ? "Creating..." : "Create Invite"}
                      </Button>
                    </DialogFooter>
                  </form>
                </DialogContent>
              </Dialog>
            )}
          </CardHeader>
          <CardContent>
            {membersLoading ? (
              <p className="text-slate-500">Loading members...</p>
            ) : (
              <>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Name</TableHead>
                      <TableHead>Email</TableHead>
                      <TableHead>Role</TableHead>
                      <TableHead>Joined</TableHead>
                      {isAdmin && <TableHead className="text-right">Actions</TableHead>}
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {members?.map((member) => (
                      <TableRow key={member.user_id}>
                        <TableCell>{member.display_name}</TableCell>
                        <TableCell>{member.email}</TableCell>
                        <TableCell>
                          {editingMemberId === member.user_id ? (
                            <Select
                              value={editRole}
                              onChange={(e) => setEditRole(e.target.value)}
                              onBlur={() => handleRoleChange(member.user_id, editRole)}
                              defaultValue={member.role}
                            >
                              {ROLES.map((role) => (
                                <option key={role} value={role}>
                                  {getRoleDisplayName(role)}
                                </option>
                              ))}
                            </Select>
                          ) : (
                            <Badge variant={getRoleBadgeVariant(member.role)}>
                              {getRoleDisplayName(member.role)}
                            </Badge>
                          )}
                        </TableCell>
                        <TableCell>
                          {new Date(member.joined_at).toLocaleDateString()}
                        </TableCell>
                        {isAdmin && (
                          <TableCell className="text-right">
                            <div className="flex items-center justify-end gap-2">
                              {editingMemberId === member.user_id ? (
                                <>
                                  <Button
                                    variant="ghost"
                                    size="sm"
                                    onClick={() => handleRoleChange(member.user_id, editRole)}
                                  >
                                    Save
                                  </Button>
                                  <Button
                                    variant="ghost"
                                    size="sm"
                                    onClick={() => setEditingMemberId(null)}
                                  >
                                    Cancel
                                  </Button>
                                </>
                              ) : (
                                <>
                                  <Button
                                    variant="ghost"
                                    size="sm"
                                    onClick={() => {
                                      setEditingMemberId(member.user_id);
                                      setEditRole(member.role);
                                    }}
                                  >
                                    Edit Role
                                  </Button>
                                  {currentUserMembership?.user_id !== member.user_id && (
                                    <Button
                                      variant="ghost"
                                      size="sm"
                                      className="text-red-600 hover:text-red-700"
                                      onClick={() => handleRemoveMember(member.user_id)}
                                      disabled={removeMemberMutation.isPending}
                                    >
                                      Remove
                                    </Button>
                                  )}
                                </>
                              )}
                            </div>
                          </TableCell>
                        )}
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
                {!members?.length && (
                  <p className="text-center text-slate-500 py-8">No members found.</p>
                )}
              </>
            )}
          </CardContent>
        </Card>

        {/* Organization Info Section */}
        <Card>
          <CardHeader>
            <CardTitle>Organization Info</CardTitle>
            <CardDescription>Basic organization details</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div>
              <Label>Organization ID</Label>
              <Input value={orgId} readOnly className="mt-1 bg-slate-50" />
            </div>
            <div>
              <Label>Your Role</Label>
              <Badge variant={getRoleBadgeVariant(currentUserMembership?.role || "viewer")}>
                {getRoleDisplayName(currentUserMembership?.role || "viewer")}
              </Badge>
            </div>
            <div>
              <Label>Total Members</Label>
              <p className="text-2xl font-semibold">{members?.length || 0}</p>
            </div>
          </CardContent>
        </Card>
      </div>
    </section>
  );
}