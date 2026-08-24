import type { Metadata } from "next";
import { LandingPage } from "@/components/landing-page";

export const metadata: Metadata = {
  title: "开始你的互动叙事",
  description: "探索可保存、可持续生长的互动文字世界，并让每一次选择留下痕迹。",
};

export default function Home() {
  return <LandingPage />;
}
