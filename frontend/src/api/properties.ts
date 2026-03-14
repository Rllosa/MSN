import client from "./client";

export interface Property {
  id: string;
  name: string;
  slug: string;
  beds24_property_id: number | null;
}

export async function getProperties(): Promise<Property[]> {
  const res = await client.get<Property[]>("/properties/");
  return res.data;
}
