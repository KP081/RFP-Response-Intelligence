import { createContext, useContext, useEffect, useState, ReactNode } from "react";
import { useNavigate, useLocation } from "react-router-dom";

import { apiClient } from "@/api/client";

interface User {
  id: string;
  email: string;
  display_name: string;
  external_idp_subject: string | null;
  created_at: string;
}

interface OrgMembership {
  org_id: string;
  org_name: string;
  role: string;
  user_id: string;
}

interface MeResponse {
  user: User;
  memberships: OrgMembership[];
}

interface AuthContextType {
  user: User | null;
  memberships: OrgMembership[];
  currentOrg: OrgMembership | null;
  isLoading: boolean;
  isAuthenticated: boolean;
  login: (redirectUri?: string) => void;
  logout: () => Promise<void>;
  setCurrentOrg: (orgId: string) => void;
  refreshAuth: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [memberships, setMemberships] = useState<OrgMembership[]>([]);
  const [currentOrg, setCurrentOrgState] = useState<OrgMembership | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const navigate = useNavigate();

  const refreshAuth = async () => {
    try {
      const response = await apiClient.get<MeResponse>("/auth/me");
      setUser(response.user);
      setMemberships(response.memberships);

      // Try to restore current org from localStorage or use first membership
      const savedOrgId = localStorage.getItem("currentOrgId");
      if (savedOrgId) {
        const savedMembership = response.memberships.find(
          (m: OrgMembership) => m.org_id === savedOrgId
        );
        if (savedMembership) {
          setCurrentOrgState(savedMembership);
        } else if (response.memberships.length > 0) {
          setCurrentOrgState(response.memberships[0]);
        }
      } else if (response.memberships.length > 0) {
        setCurrentOrgState(response.memberships[0]);
      }
    } catch {
      setUser(null);
      setMemberships([]);
      setCurrentOrgState(null);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    refreshAuth();
  }, []);

  const login = (returnTo?: string) => {
    const params = returnTo ? `?return_to=${encodeURIComponent(returnTo)}` : "";
    window.location.href = `${import.meta.env.VITE_API_BASE_URL}/auth/login${params}`;
  };

  const logout = async () => {
    try {
      await apiClient.post("/auth/logout");
    } catch {
      // Ignore errors
    } finally {
      setUser(null);
      setMemberships([]);
      setCurrentOrgState(null);
      localStorage.removeItem("currentOrgId");
      navigate("/login");
    }
  };

  const setCurrentOrg = (orgId: string) => {
    const membership = memberships.find((m) => m.org_id === orgId);
    if (membership) {
      setCurrentOrgState(membership);
      localStorage.setItem("currentOrgId", orgId);
    }
  };

  const value: AuthContextType = {
    user,
    memberships,
    currentOrg,
    isLoading,
    isAuthenticated: !!user,
    login,
    logout,
    setCurrentOrg,
    refreshAuth,
  };

  return (
    <AuthContext.Provider value={value}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}

export function useRequireAuth() {
  const { isAuthenticated, isLoading, login } = useAuth();
  const location = useLocation();

  useEffect(() => {
    if (!isLoading && !isAuthenticated) {
      login(location.pathname + location.search);
    }
  }, [isAuthenticated, isLoading, login, location]);

  return { isAuthenticated, isLoading };
}