import { Navigate, Outlet } from "react-router-dom";
import { useAuthStore } from "../store/auth";

/** Redirects to /login if no access token is present in the auth store. */
export default function RequireAuth() {
  const accessToken = useAuthStore((s) => s.accessToken);

  if (!accessToken) {
    return <Navigate to="/login" replace />;
  }

  return <Outlet />;
}
