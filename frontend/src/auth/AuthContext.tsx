import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { Navigate, useLocation } from "react-router-dom";
import { getCurrentUser, logoutRequest } from "../api/auth";
import { AUTH_REQUIRED_EVENT } from "../api/client";
import { FullPageLoading } from "../components/LoadingState";
import type { User } from "../types/auth";

interface AuthContextValue {
  user: User | null;
  /** 首次加载是否正在恢复登录状态。 */
  initializing: boolean;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [initializing, setInitializing] = useState(true);

  useEffect(() => {
    let active = true;
    const handleAuthRequired = () => {
      if (active) {
        setUser(null);
        setInitializing(false);
        // 服务端会话已无效，补充调用注销接口以删除浏览器中的 HttpOnly Cookie。
        void logoutRequest().catch(() => undefined);
      }
    };
    window.addEventListener(AUTH_REQUIRED_EVENT, handleAuthRequired);
    void getCurrentUser()
      .then((next) => {
        if (active) setUser(next);
      })
      .catch(() => {
        if (active) setUser(null);
      })
      .finally(() => {
        if (active) setInitializing(false);
      });
    return () => {
      active = false;
      window.removeEventListener(AUTH_REQUIRED_EVENT, handleAuthRequired);
    };
  }, []);

  const persist = useCallback((next: User | null) => {
    setUser(next);
  }, []);

  const logout = useCallback(async () => {
    try {
      await logoutRequest();
    } finally {
      persist(null);
    }
  }, [persist]);

  const value = useMemo<AuthContextValue>(
    () => ({ user, initializing, logout }),
    [user, initializing, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth 必须在 <AuthProvider> 内使用。");
  }
  return context;
}

/** 未登录访问业务页时跳转登录页。 */
export function RequireAuth({ children }: { children: ReactNode }) {
  const { user, initializing } = useAuth();
  const location = useLocation();

  if (initializing) {
    return <FullPageLoading />;
  }
  if (!user) {
    return <Navigate to="/login" state={{ from: location }} replace />;
  }
  return <>{children}</>;
}

/** 仅管理员可访问：非管理员跳转首页。 */
export function RequireAdmin({ children }: { children: ReactNode }) {
  const { user, initializing } = useAuth();

  if (initializing) {
    return <FullPageLoading />;
  }
  if (!user) {
    return <Navigate to="/login" replace />;
  }
  if (user.role !== "admin") {
    return <Navigate to="/search" replace />;
  }
  return <>{children}</>;
}
