import type {Session} from './types'
/** Explicit allowlist: never export ownership capability, CSRF token, cookies or private workflow state. */
export function publicReport(session:Session, grafanaLinks: {label:string;url:string}[] = []) {
 const evidenceReferences = [session.baseline, session.comparison].filter(run => run !== null).map(run => ({run_id:run!.run_id, path:`/api/sessions/${encodeURIComponent(session.id)}/evidence/${encodeURIComponent(run!.run_id)}`}))
 return {schema_version:1,mode:session.mode,state:session.state,shot_context:session.shot_context,baseline_config:session.baseline_config,comparison_config:session.comparison_config,baseline:session.baseline,comparison:session.comparison,confirmed_constraints:session.confirmed_constraints,candidate_plans:session.candidate_plans,verification:session.verification,original_baseline:session.original_baseline,history:session.history?.map(({baseline,comparison,config,verification})=>({baseline,comparison,config,verification})),finding_evidence:session.finding_evidence,evidence_references:evidenceReferences,grafana_links:grafanaLinks,disclosure:'Simulated receiver conditions; not real-world RF certification or audio restoration. Evidence links require the owning browser or a Grafana login.'}
}
export async function downloadReport(session:Session){
 let links: {label:string;url:string}[] = []
 if(session.mode==='live'){
  try{const response=await fetch(`/api/sessions/${encodeURIComponent(session.id)}/evidence-links`,{credentials:'same-origin',signal:AbortSignal.timeout(3000)});if(response.ok){const body=await response.json();links=(body.links??[]).filter((link:{label:string;url:string})=>{try{const u=new URL(link.url);return u.protocol==='https:'&&!u.username&&!u.password}catch{return false}})}}catch{/* Returned evidence remains downloadable if Grafana links are unavailable. */}
 }
 const url=URL.createObjectURL(new Blob([JSON.stringify(publicReport(session,links),null,2)],{type:'application/json'}));const anchor=document.createElement('a');anchor.href=url;anchor.download='signal-slate-report.json';anchor.click();setTimeout(()=>URL.revokeObjectURL(url),1000)
}
