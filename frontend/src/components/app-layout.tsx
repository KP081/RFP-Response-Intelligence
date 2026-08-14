import { NavLink, Outlet } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const navigation = [
  { label: "Home", to: "/" },
  { label: "Organizations", to: "/orgs/example-org" },
];

export function AppLayout() {
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
          </div>
          <div className="flex items-center gap-3">
            <span className="hidden text-sm text-slate-500 sm:inline">Not logged in</span>
            <Button asChild size="sm">
              <NavLink to="/login">Log in</NavLink>
            </Button>
          </div>
        </nav>
      </header>
      <main className="mx-auto w-full max-w-6xl px-6 py-10">
        <Outlet />
      </main>
    </div>
  );
}
