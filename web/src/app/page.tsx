import { redirect } from "next/navigation";
import { SPORT_TABS } from "@/lib/sports";

export default function Home() {
  redirect(`/s/${SPORT_TABS[0].slug}`);
}
