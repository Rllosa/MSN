import client from "./client";

interface TokenResponse {
  access_token: string;
}

export async function postLogin(
  email: string,
  password: string,
): Promise<TokenResponse> {
  const res = await client.post<TokenResponse>("/auth/login", {
    email,
    password,
  });
  return res.data;
}

// Named postRefresh (not "refresh") to avoid shadowing the browser's Cache API
export async function postRefresh(): Promise<TokenResponse> {
  const res = await client.post<TokenResponse>("/auth/refresh");
  return res.data;
}

export async function postLogout(): Promise<void> {
  await client.post("/auth/logout");
}
