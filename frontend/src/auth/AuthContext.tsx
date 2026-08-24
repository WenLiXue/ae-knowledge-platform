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
import { logoutRequest, passwordLogin } from "../api/auth";
import { FullPageLoading } from "../components/LoadingState";
import type { User } from "../types/auth";

const STORAGE_KEY = "ae-knowledge.auth.user";

interface AuthContextValue {
  user: User | null;
  /** 首次加载是否正在恢复登录状态。 */
  initializing: boolean;
  login: (username: string, password: string) => Promise<void>;
  loginWithFeishu: () => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

function readStoredUser(): User | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    return JSON.parse(raw) as User;
  } catch {
    return null;
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(() => readStoredUser());
  const [initializing, setInitializing] = useState(true);

  useEffect(() => {
    // MOCK: 真实实现会在加载时调用 GET /api/v1/auth/me 恢复会话。
    const timer = setTimeout(() => setInitializing(false), 300);
    return () => clearTimeout(timer);
  }, []);

  const persist = useCallback((next: User | null) => {
    setUser(next);
    if (next) {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
    } else {
      localStorage.removeItem(STORAGE_KEY);
    }
  }, []);

  const login = useCallback(
    async (username: string, password: string) => {
      const next = await passwordLogin(username, password);
      persist(next);
    },
    [persist],
  );

  const loginWithFeishu = useCallback(async () => {
    // MOCK: 真实实现走飞书授权回调后登录；当前直接模拟登录成功。
    const next: User = {
      id: "00000000-0000-0000-0000-000000000001",
      username: "demo",
      display_name: "演示用户",
      role: "admin",
      feishu_bound: true,
    };
    persist(next);
  }, [persist]);

  const logout = useCallback(async () => {
    try {
      await logoutRequest();
    } finally {
      persist(null);
    }
  }, [persist]);

  const value = useMemo<AuthContextValue>(
    () => ({ user, initializing, login, loginWithFeishu, logout }),
    [user, initializing, login, loginWithFeishu, logout],
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
