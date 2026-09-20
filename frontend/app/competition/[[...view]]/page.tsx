import { notFound } from "next/navigation";
import { CompetitionStudio } from "@/components/competition/studio";

export default async function Page({ params }: { params: Promise<{ view?: string[] }> }) {
  const { view = [] } = await params;
  const path = view.join("/");
  if (!["", "system/heart", "system/metabolic", "system/kidney", "plan/heart", "plan/metabolic", "plan/kidney", "plan/all"].includes(path)) notFound();
  return <CompetitionStudio page={path} />;
}
