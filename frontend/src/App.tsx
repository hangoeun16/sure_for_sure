import { useEffect, useState } from "react";
import { api } from "./api/client";
import type { Analysis, EncounterListItem } from "./api/types";
import { TopBar } from "./components/TopBar";
import { EncounterPicker } from "./pages/EncounterPicker";
import { EncounterReview } from "./pages/EncounterReview";
import { HumanReviewApp } from "./review/HumanReviewApp";

export default function App() {
  if (window.location.pathname.startsWith("/human-review")) return <HumanReviewApp />;
  return <ProductApp />;
}

function ProductApp() {
  const [encounters, setEncounters] = useState<EncounterListItem[]>([]);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [error, setError] = useState("");
  useEffect(() => { api.encounters().then(setEncounters).catch(reason => setError(String(reason))); }, []);
  const open = async (id: string) => { setError(""); try { setAnalysis(await api.analyze(id)); } catch (reason) { setError(String(reason)); } };
  return <><TopBar />{error && <div className="shell"><p className="error">{error}</p></div>}{analysis ? <EncounterReview analysis={analysis} onBack={() => setAnalysis(null)} /> : <EncounterPicker encounters={encounters} onOpen={open} />}</>;
}
