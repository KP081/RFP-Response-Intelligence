import { useEffect } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { useAuth } from "@/context/AuthContext";

export function AuthCallback() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { refreshAuth } = useAuth();

  useEffect(() => {
    const handleCallback = async () => {
      // The backend sets cookies via the callback redirect
      // We just need to refresh auth state and redirect to home or intended page
      await refreshAuth();
      const redirectTo = searchParams.get("redirect") || "/";
      navigate(redirectTo, { replace: true });
    };

    handleCallback();
  }, [navigate, searchParams, refreshAuth]);

  return (
    <div className="flex min-h-screen items-center justify-center">
      <div className="text-center">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600 mx-auto"></div>
        <p className="mt-4 text-slate-600">Completing sign in...</p>
      </div>
    </div>
  );
}