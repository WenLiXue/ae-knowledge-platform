import { RouterProvider } from "react-router-dom";
import { AuthProvider } from "../auth/AuthContext";
import { router } from "./router";

/** 应用根组件：挂载 AuthProvider（会话状态）与路由。 */
export default function App() {
  return (
    <AuthProvider>
      <RouterProvider router={router} />
    </AuthProvider>
  );
}
