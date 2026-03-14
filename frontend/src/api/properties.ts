import client from "./client";

export interface Property {
  id: string;
  name: string;
  slug: string;
}

export async function getProperties(): Promise<Property[]> {
  const res = await client.get<Property[]>("/properties/");
  return res.data;
}
