import { useParams, useNavigate } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card";

export function OrganizationPage() {
  const { orgId } = useParams();
  const navigate = useNavigate();

  const handleGoToSettings = () => {
    navigate(`/orgs/${orgId}/settings`);
  };

  const handleGoToDocuments = () => {
    navigate(`/orgs/${orgId}/documents`);
  };

  return (
    <section>
      <div className="mb-6">
        <p className="text-sm font-medium text-slate-500">Organization</p>
        <h1 className="mt-2 text-3xl font-semibold tracking-tight">{orgId}</h1>
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Documents</CardTitle>
            <CardDescription>Upload and manage documents</CardDescription>
          </CardHeader>
          <CardContent>
            <Button onClick={handleGoToDocuments} className="w-full">Go to Documents</Button>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Settings</CardTitle>
            <CardDescription>Manage organization settings and members</CardDescription>
          </CardHeader>
          <CardContent>
            <Button onClick={handleGoToSettings} className="w-full">Go to Settings</Button>
          </CardContent>
        </Card>
      </div>
    </section>
  );
}
