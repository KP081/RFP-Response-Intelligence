import { createBrowserRouter } from "react-router-dom";

import { AppLayout } from "@/components/app-layout";
import { HomePage } from "@/pages/home-page";
import { LoginPage } from "@/pages/login-page";
import { OrganizationPage } from "@/pages/organization-page";
import { AuthCallback } from "@/pages/auth-callback-page";
import { ProtectedRoute } from "@/components/ProtectedRoute";

export const router = createBrowserRouter([
  {
    element: <AppLayout />,
    children: [
      { index: true, element: <ProtectedRoute><HomePage /></ProtectedRoute> },
      { path: "login", element: <LoginPage /> },
      { path: "auth/callback", element: <AuthCallback /> },
      { path: "orgs/:orgId", element: <ProtectedRoute><OrganizationPage /></ProtectedRoute> },
    ],
  },
]);
