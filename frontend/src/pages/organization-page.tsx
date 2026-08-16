import { useParams, useNavigate } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card";

export function OrganizationPage() {
  const { orgId } = useParams();
  const navigate = useNavigate();

  const handleGoToSettings = () => {
    navigate(`/orgs/${orgId}/settings`);
  };

  return (
    <section>
      <div className="mb-6">
        <p className="text-sm font-medium text-slate-500">Organization</p>
        <h1 className="mt-2 text-3xl font-semibold tracking-tight">{orgId}</h1>
      </div>
      <Card>
        <CardHeader>
          <CardTitle>Organization Dashboard</CardTitle>
          <CardDescription>Manage your organization settings and members</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="space-y-4">
            <Button onClick={handleGoToSettings}>Go to Settings</Button>
            <p className="text-slate-600">
              Organization content will be added in a later feature task.
            </p>
          </div>
        </CardContent>
      </Card>
    </section>
  );
}
