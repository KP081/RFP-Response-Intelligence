import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiClient, ApiError } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, CardTitle, CardDescription, CardContent, CardFooter } from "@/components/ui/card";
import { useAuth } from "@/context/AuthContext";

interface InviteAcceptResponse {
  org_id: string;
  org_name: string;
  role: string;
  message: string;
}

export function InviteAcceptPage() {
  const { token } = useParams<{ token: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { refreshAuth } = useAuth();

  const [status, setStatus] = useState<"loading" | "success" | "error">("loading");
  const [message, setMessage] = useState("");
  const [orgName, setOrgName] = useState("");
  const [role, setRole] = useState("");

  const acceptInviteMutation = useMutation({
    mutationFn: async (token: string) => {
      const response = await apiClient.post<InviteAcceptResponse>(`/invites/${token}/accept`);
      return response;
    },
    onSuccess: async (data) => {
      setStatus("success");
      setMessage(data.message);
      setOrgName(data.org_name);
      setRole(data.role);
      await refreshAuth();
      queryClient.invalidateQueries({ queryKey: ["org-members", data.org_id] });
    },
    onError: (error: ApiError) => {
      setStatus("error");
      setMessage(error.details?.message as string || error.message || "Failed to accept invite");
    },
  });

  useEffect(() => {
    if (token) {
      acceptInviteMutation.mutate(token);
    }
  }, [token]);

  if (status === "loading") {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <Card className="w-full max-w-md">
          <CardContent className="py-12 text-center">
            <div className="animate-spin rounded-full h-12 w-12 border-4 border-blue-500 border-t-transparent mx-auto mb-4" />
            <p className="text-slate-600">Accepting invite...</p>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <Card className="w-full max-w-md">
        <CardHeader className="text-center">
          <CardTitle>
            {status === "success" ? "Invite Accepted!" : "Invite Failed"}
          </CardTitle>
          <CardDescription>
            {status === "success"
              ? `You have joined ${orgName} as ${role.replace(/_/g, " ")}.`
              : message}
          </CardDescription>
        </CardHeader>
        <CardContent className="text-center">
          {status === "success" && (
            <p className="text-sm text-slate-600 mb-4">
              You can now access the organization from the org switcher.
            </p>
          )}
        </CardContent>
        <CardFooter className="flex justify-center">
          {status === "success" ? (
            <Button onClick={() => navigate(`/orgs/${token}`)}>Go to Organization</Button>
          ) : (
            <Button variant="outline" onClick={() => navigate("/login")}>
              Go to Login
            </Button>
          )}
        </CardFooter>
      </Card>
    </div>
  );
}