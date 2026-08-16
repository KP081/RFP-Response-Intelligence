import { NavLink, Outlet, useNavigate } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { useAuth } from "@/context/AuthContext";

const navigation = [
  { label: "Home", to: "/" },
];

export function AppLayout() {
  const { user, memberships, currentOrg, logout, setCurrentOrg, isAuthenticated } = useAuth();
  const navigate = useNavigate();

  const handleLogout = async () => {
    await logout();
  };

  const handleOrgChange = (orgId: string) => {
    setCurrentOrg(orgId);
    navigate(`/orgs/${orgId}`);
  };

  return (
    <div className="min-h-screen">
      <header className="border-b bg-white">
        <nav
          aria-label="Main navigation"
          className="mx-auto flex max-w-6xl items-center justify-between gap-6 px-6 py-4"
        >
          <NavLink className="text-base font-semibold tracking-tight" to="/">
            RFP Response Intelligence
          </NavLink>
          <div className="flex items-center gap-1">
            {navigation.map((item) => (
              <NavLink
                className={({ isActive }) =>
                  cn(
                    "rounded-md px-3 py-2 text-sm text-slate-600 hover:bg-slate-100 hover:text-slate-950",
                    isActive && "bg-slate-100 text-slate-950",
                  )
                }
                key={item.to}
                to={item.to}
              >
                {item.label}
              </NavLink>
            ))}
            {isAuthenticated && currentOrg && (
              <NavLink
                to={`/orgs/${currentOrg.org_id}/settings`}
                className={({ isActive }) =>
                  cn(
                    "rounded-md px-3 py-2 text-sm text-slate-600 hover:bg-slate-100 hover:text-slate-950",
                    isActive && "bg-slate-100 text-slate-950",
                  )
                }
              >
                Organization Settings
              </NavLink>
            )}
          </div>
          <div className="flex items-center gap-3">
            {isAuthenticated && currentOrg && (
              <div className="flex items-center gap-3">
                <select
                  value={currentOrg.org_id}
                  onChange={(e) => handleOrgChange(e.target.value)}
                  className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm text-slate-900 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                >
                  {memberships.map((m) => (
                    <option key={m.org_id} value={m.org_id}>
                      {m.org_name} ({m.role})
                    </option>
                  ))}
                </select>
                <span className="hidden text-sm text-slate-500 sm:inline">
                  {user?.display_name} ({user?.email})
                </span>
                <Button asChild size="sm" variant="ghost" onClick={handleLogout}>
                  <NavLink to="/login">Log out</NavLink>
                </Button>
              </div>
            )}
            {!isAuthenticated && (
              <Button asChild size="sm">
                <NavLink to="/login">Log in</NavLink>
              </Button>
            )}
          </div>
        </nav>
      </header>
      <main className="mx-auto w-full max-w-6xl px-6 py-10">
        <Outlet />
      </main>
    </div>
  );
}
