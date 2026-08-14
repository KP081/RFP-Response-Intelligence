import { createBrowserRouter } from "react-router-dom";

import { AppLayout } from "@/components/app-layout";
import { HomePage } from "@/pages/home-page";
import { LoginPage } from "@/pages/login-page";
import { OrganizationPage } from "@/pages/organization-page";

export const router = createBrowserRouter([
  {
    element: <AppLayout />,
    children: [
      { index: true, element: <HomePage /> },
      { path: "login", element: <LoginPage /> },
      { path: "orgs/:orgId", element: <OrganizationPage /> },
    ],
  },
]);
