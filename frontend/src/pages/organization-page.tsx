import { useParams } from "react-router-dom";

export function OrganizationPage() {
  const { orgId } = useParams();

  return (
    <section>
      <p className="text-sm font-medium text-slate-500">Organization</p>
      <h1 className="mt-2 text-3xl font-semibold tracking-tight">{orgId}</h1>
      <p className="mt-3 text-slate-600">
        Organization content will be added in a later feature task.
      </p>
    </section>
  );
}
