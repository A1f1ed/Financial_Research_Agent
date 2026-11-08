export type EvaluationDecision={approved:false}|{approved:true;run_id:string};
export function parseEvaluationDecision(result:unknown):EvaluationDecision|null{
  try{
    let value=result;
    for(let i=0;i<2&&typeof value==="string";i++){
      if(value.length>4096)return null;
      value=JSON.parse(value);
    }
    if(!value||typeof value!=="object")return null;
    const decision=value as Record<string,unknown>;
    if(decision.approved===false)return {approved:false};
    if(decision.approved===true&&typeof decision.run_id==="string"&&/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i.test(decision.run_id))return {approved:true,run_id:decision.run_id};
  }catch{/* Incomplete native history is not an approval. */}
  return null;
}
