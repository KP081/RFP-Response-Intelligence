import { Outlet } from "react-router-dom";

import { AuthProvider } from "@/context/AuthContext";

export function AuthWrapper() {
  return (
    <AuthProvider>
      <Outlet />
    </AuthProvider>
  );
}