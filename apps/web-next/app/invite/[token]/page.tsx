"use client";

import { useParams } from "next/navigation";
import { ReleaseDetail } from "@/components/ReleaseDetail";

export default function Invite() {
  const { token } = useParams<{ token: string }>();
  return <ReleaseDetail endpoint={`/catalog/shared/${token}`} shareToken={token} />;
}
