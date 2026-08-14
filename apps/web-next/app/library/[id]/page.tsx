"use client";

import { useParams } from "next/navigation";
import { ReleaseDetail } from "@/components/ReleaseDetail";

export default function Detail() {
  const { id } = useParams<{ id: string }>();
  return <ReleaseDetail endpoint={`/catalog/releases/${id}`} />;
}
