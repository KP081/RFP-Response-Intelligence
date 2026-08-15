import { useSearchParams } from "react-router-dom";

import { useAuth } from "@/context/AuthContext";
import { Button } from "@/components/ui/button";

export function LoginPage() {
  const [searchParams] = useSearchParams();
  const { login, isLoading, isAuthenticated } = useAuth();

  const redirectTo = searchParams.get("redirect") || "/";

  const handleLogin = () => {
    login(redirectTo);
  };

  if (isAuthenticated) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600 mx-auto"></div>
      </div>
    );
  }

  return (
    <section className="max-w-md mx-auto">
      <p className="text-sm font-medium text-slate-500">Authentication</p>
      <h1 className="mt-2 text-3xl font-semibold tracking-tight">Log in</h1>
      <p className="mt-3 text-slate-600">
        Sign in with your organization account to access RFP Response Intelligence.
      </p>
      <div className="mt-8">
        <Button
          onClick={handleLogin}
          disabled={isLoading}
          className="w-full"
          size="lg"
        >
          {isLoading ? "Redirecting..." : "Sign in with SSO"}
        </Button>
      </div>
      <p className="mt-6 text-center text-sm text-slate-500">
        For local development, this redirects to Keycloak at
        <code className="text-slate-700"> http://localhost:8081 </code>
      </p>
    </section>
  );
}
