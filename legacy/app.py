"""
app.py — Sure for Sure — custom web app (Flask). NOT pre-computed, NOT out-of-the-box.

Feed it a competition encounter (upload a JSON line, or pick one from the loaded
dataset) and the REAL engine runs live: parse FHIR -> detect divergence -> route.

Run:  python3 app.py     then open http://127.0.0.1:5000
"""
import json, os
from flask import Flask, request, jsonify, render_template_string
from analyze import analyze_encounter

app = Flask(__name__)

DATA_PATH = os.environ.get("SURE_DATA",
    "data/synthetic-ambient-fhir-25.jsonl")


def _load_dataset():
    if not os.path.exists(DATA_PATH):
        return []
    out = []
    for i, line in enumerate(open(DATA_PATH)):
        r = json.loads(line)
        out.append({"idx": i, "title": r["metadata"].get("visit_title", f"#{i}")})
    return out


@app.route("/")
def index():
    return render_template_string(PAGE, encounters=_load_dataset())


@app.route("/analyze", methods=["POST"])
def analyze():
    # either an uploaded JSON encounter, or an index into the loaded dataset
    if "idx" in request.json:
        line = open(DATA_PATH).readlines()[int(request.json["idx"])]
        record = json.loads(line)
    else:
        record = request.json["encounter"]
    return jsonify(analyze_encounter(record))   # <-- REAL engine runs here


PAGE = r"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Sure for Sure</title>
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;600;700&family=Inter:wght@400;450;500;600&family=IBM+Plex+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<style>
:root{--cream:#F4F6F5;--white:#fff;--ink:#16262B;--muted:#5C6E74;--faint:#93A0A2;
--hair:#E1E7E5;--teal:#0E7C86;--teal-soft:#E7F3F3;--ask:#B5641E;--ask-bg:#FBF1E6;
--verify:#2C6E9B;--verify-bg:#EAF1F7;--suppress:#5E8065;--suppress-bg:#EEF3EE;
--disp:'Space Grotesk',sans-serif;--sans:'Inter',sans-serif;--mono:'IBM Plex Mono',monospace;}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--cream);color:var(--ink);font-family:var(--sans);font-size:15px;line-height:1.55}
.app{max-width:1080px;margin:0 auto;padding:clamp(18px,3vw,34px)}
.topbar{display:flex;align-items:center;gap:12px;margin-bottom:22px}
.logo{display:flex;align-items:center;gap:9px;font-family:var(--disp);font-weight:700;font-size:19px}
.logo .chk{width:26px;height:26px;border-radius:7px;background:var(--teal);color:#fff;display:flex;align-items:center;justify-content:center}
.badge-pill{font-family:var(--mono);font-size:10.5px;color:var(--teal);background:var(--teal-soft);border-radius:999px;padding:4px 11px;font-weight:600}
.lead{font-family:var(--disp);font-weight:600;font-size:clamp(20px,3vw,26px);letter-spacing:-.02em;margin-bottom:6px}
.sub{color:var(--muted);font-size:14px;margin-bottom:22px;max-width:64ch}
.picker{background:var(--white);border:1px solid var(--hair);border-radius:14px;padding:18px 20px;margin-bottom:18px}
.picker h3{font-size:11.5px;letter-spacing:.08em;text-transform:uppercase;color:var(--faint);font-weight:600;margin-bottom:12px}
.row{display:flex;gap:10px;flex-wrap:wrap;align-items:center}
select{font-family:var(--sans);font-size:14px;padding:9px 12px;border:1px solid var(--hair);border-radius:9px;background:var(--white);color:var(--ink);min-width:320px}
button{font-family:var(--sans);font-size:14px;font-weight:600;padding:9px 18px;border:none;border-radius:9px;background:var(--ink);color:#fff;cursor:pointer}
button:hover{background:var(--teal)}
.or{color:var(--faint);font-size:13px}
input[type=file]{font-size:13px;font-family:var(--sans)}
.engine-tag{font-family:var(--mono);font-size:10.5px;color:var(--suppress);background:var(--suppress-bg);border-radius:999px;padding:4px 11px;font-weight:600;margin-left:auto}
#result{margin-top:8px}
.rhead{display:flex;align-items:baseline;gap:12px;margin-bottom:6px}
.rhead .t{font-family:var(--disp);font-weight:600;font-size:18px}
.rhead .m{font-family:var(--mono);font-size:12px;color:var(--faint)}
.stats{display:flex;gap:10px;margin:16px 0}
.stat{flex:1;background:var(--white);border:1px solid var(--hair);border-radius:12px;padding:13px 15px}
.stat .n{font-family:var(--mono);font-size:24px;font-weight:600}
.stat .l{font-size:11.5px;color:var(--faint);text-transform:uppercase;letter-spacing:.05em;margin-top:2px}
.stat.ask .n{color:var(--ask)}.stat.verify .n{color:var(--verify)}.stat.suppress .n{color:var(--suppress)}
.card{background:var(--white);border:1px solid var(--hair);border-left:4px solid var(--edge);border-radius:12px;padding:16px 18px;margin-bottom:12px}
.card.ask{--edge:var(--ask)}.card.verify{--edge:var(--verify)}.card.suppress{--edge:var(--suppress)}
.card .top{display:flex;justify-content:space-between;align-items:center;gap:10px;margin-bottom:10px}
.card .dt{font-family:var(--mono);font-size:11.5px;padding:3px 9px;border-radius:6px;background:#EEF2F1;color:var(--muted)}
.chip{font-size:12px;font-weight:600;padding:4px 11px;border-radius:999px}
.chip.ask{color:var(--ask);background:var(--ask-bg)}.chip.verify{color:var(--verify);background:var(--verify-bg)}.chip.suppress{color:var(--suppress);background:var(--suppress-bg)}
.assess{font-size:14px;font-weight:500;margin-bottom:8px}
.evi{font-family:var(--mono);font-size:12px;color:var(--muted);background:#F7F9F8;padding:9px 11px;border-radius:8px;margin-bottom:8px}
.owner{font-size:12.5px;color:var(--faint);margin-bottom:10px}
.owner b{color:var(--muted)}
.q{border-top:1px dashed var(--hair);padding-top:10px}
.q .k{font-family:var(--mono);font-size:10.5px;text-transform:uppercase;letter-spacing:.06em;color:var(--faint);display:block;margin-bottom:4px}
.q .txt{font-size:14px;color:var(--ink)}
.empty{color:var(--faint);font-size:14px;padding:20px;text-align:center}
.foot{margin-top:18px;color:var(--faint);font-size:12px;border-top:1px solid var(--hair);padding-top:14px;line-height:1.6}
</style></head><body>
<div class="app">
  <div class="topbar">
    <div class="logo"><span class="chk">&#10003;</span> Sure for Sure</div>
    <span class="badge-pill">live engine</span>
  </div>
  <div class="lead">Feed an encounter &rarr; the pipeline runs</div>
  <div class="sub">Pick a competition encounter (or upload one). Sure for Sure parses the FHIR,
    detects certainty&ndash;evidence divergence, and routes each finding &mdash;
    live, not pre-computed.</div>

  <div class="picker">
    <h3>Input</h3>
    <div class="row">
      <select id="sel">
        {% for e in encounters %}<option value="{{e.idx}}">#{{e.idx}} — {{e.title}}</option>{% endfor %}
      </select>
      <button onclick="runIdx()">Analyze</button>
      <span class="or">or</span>
      <input type="file" id="file" accept=".json,.jsonl">
      <button onclick="runFile()">Upload &amp; analyze</button>
      <span class="engine-tag" id="etag" style="display:none">engine: live</span>
    </div>
  </div>

  <div id="result"></div>

  <div class="foot">
    Sure for Sure never issues a verdict &mdash; it suggests a question or a record task; judgment stays
    with the clinician. Certainty is estimated from language, not asserted as true belief.
    Findings above are produced by the running engine on the encounter you selected.
  </div>
</div>
<script>
async function post(body){
  const r = await fetch('/analyze',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  return r.json();
}
function runIdx(){ post({idx: document.getElementById('sel').value}).then(render); }
function runFile(){
  const f = document.getElementById('file').files[0];
  if(!f){ alert('Choose a .json encounter first'); return; }
  const rd = new FileReader();
  rd.onload = () => {
    let enc; try{ enc = JSON.parse(rd.result.split('\n')[0]); }catch(e){ alert('Not valid JSON'); return; }
    post({encounter: enc}).then(render);
  };
  rd.readAsText(f);
}
function render(d){
  document.getElementById('etag').style.display='inline-block';
  const s=d.stats;
  let html = `<div class="rhead"><span class="t">${d.title}</span>
    <span class="m">${d.date} · ${d.n_encounters} encounters · ${d.med_count} meds on file</span></div>`;
  html += `<div class="stats">
    <div class="stat ask"><div class="n">${s.surfaced}</div><div class="l">To surface</div></div>
    <div class="stat verify"><div class="n">${s.verify}</div><div class="l">To reconcile</div></div>
    <div class="stat suppress"><div class="n">${s.suppressed}</div><div class="l">Suppressed</div></div></div>`;
  if(!d.cards.length){ html += `<div class="empty">No divergence detected in this encounter — nothing to surface.</div>`; }
  d.cards.forEach(c=>{
    html += `<div class="card ${c.route_class}">
      <div class="top"><span class="dt">${c.divergence}</span><span class="chip ${c.route_class}">${c.route_label}</span></div>
      <div class="assess">${c.assessment}</div>
      <div class="evi">${c.clinical_course}</div>
      <div class="owner">owner: <b>${c.owner}</b> · ${c.divergence_desc}</div>`;
    if(c.question){ html += `<div class="q"><span class="k">${c.route_class==='verify'?'Record task':'Suggested question'}</span><span class="txt">${c.question}</span></div>`; }
    html += `</div>`;
  });
  document.getElementById('result').innerHTML = html;
}
</script></body></html>"""

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
