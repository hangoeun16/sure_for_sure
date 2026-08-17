export function EncounterHeader({ id, onBack }: { id: string; onBack: () => void }) {
  return <div className="hero"><div><button className="back" onClick={onBack}>← All encounters</button><h1>Before you sign</h1><p>Review claim-specific confidence, record divergence, later resolution, and the remaining owner.</p></div><span className="technical">{id}</span></div>;
}
