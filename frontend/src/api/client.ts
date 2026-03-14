import axios from "axios";
import { useAuthStore } from "../store/auth";

const client = axios.create({
  baseURL: "/api",
  withCredentials: true, // send httpOnly refresh token cookie on every request
});

// Inject Bearer token from in-memory store on every request
client.interceptors.request.use((config) => {
  const token = useAuthStore.getState().accessToken;
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// On 401: try refresh once → retry original request → redirect to /login if refresh fails
client.interceptors.response.use(
  (response) => response,
  async (error) => {
    const original = error.config as typeof error.config & {
      _retry?: boolean;
    };

    // Don't retry refresh calls — they're already a last-resort auth attempt
    const isRefreshCall = original.url?.includes("/auth/refresh");
    if (error.response?.status === 401 && !original._retry && !isRefreshCall) {
      original._retry = true;
      try {
        // Import lazily to avoid circular dependency between client ↔ auth
        const { postRefresh } = await import("./auth");
        const { access_token } = await postRefresh();
        useAuthStore.getState().setToken(access_token);
        original.headers = {
          ...original.headers,
          Authorization: `Bearer ${access_token}`,
        };
        return client(original);
      } catch {
        useAuthStore.getState().logout();
        window.location.href = "/login";
      }
    }

    return Promise.reject(error);
  },
);

export default client;
