import { createBrowserRouter } from "react-router-dom";

import { AppLayout } from "@/components/app-layout";
import { HomePage } from "@/pages/home-page";
import { LoginPage } from "@/pages/login-page";
import { OrganizationPage } from "@/pages/organization-page";
import { OrgSettingsPage } from "@/pages/org-settings-page";
import { InviteAcceptPage } from "@/pages/invite-accept-page";
import { AuthCallback } from "@/pages/auth-callback-page";
import { DocumentsPage } from "@/pages/documents-page";
import { SearchPage } from "@/pages/search-page";
import { AuditLogPage } from "@/pages/audit-log-page";
import { ProtectedRoute } from "@/components/ProtectedRoute";

export const router = createBrowserRouter([
  {
    element: <AppLayout />,
    children: [
      { index: true, element: <ProtectedRoute><HomePage /></ProtectedRoute> },
      { path: "login", element: <LoginPage /> },
      { path: "auth/callback", element: <AuthCallback /> },
      { path: "invites/:token", element: <InviteAcceptPage /> },
      { path: "orgs/:orgId", element: <ProtectedRoute><OrganizationPage /></ProtectedRoute> },
      { path: "orgs/:orgId/settings", element: <ProtectedRoute><OrgSettingsPage /></ProtectedRoute> },
      { path: "orgs/:orgId/documents", element: <ProtectedRoute><DocumentsPage /></ProtectedRoute> },
      { path: "orgs/:orgId/search", element: <ProtectedRoute><SearchPage /></ProtectedRoute> },
      { path: "orgs/:orgId/audit-log", element: <ProtectedRoute><AuditLogPage /></ProtectedRoute> },
    ],
  },
]);
