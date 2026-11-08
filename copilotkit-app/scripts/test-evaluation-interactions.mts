import assert from "node:assert/strict";
import {parseEvaluationImport} from "../src/components/evaluations/import-contract.ts";
import {parseEvaluationDecision} from "../src/components/evaluations/decision.ts";

const contract={version:"synthetic-qa",split_policy:{},default_scope:{as_of:"2026-10-31"},cases:[
  {id:"original-page",question:"Check the original units",category:"financial",split:"development",evidence:{original:[2]},expected:{note:"Human reference must be retained"}},
  {id:"frozen",question:"Inspect only with explicit human reveal",category:"vision",split:"acceptance"},
]};
const parsed=parseEvaluationImport(contract);
assert.equal(parsed.kind,"legacy");
if(parsed.kind==="legacy"){
  assert.deepEqual(parsed.payload.cases[1].evidence,{});
  assert.deepEqual(parsed.payload.cases[0].expected,contract.cases[0].expected);
  assert.equal(parsed.payload.cases[1].split,"acceptance");
}
for(const malformed of [null,[],"json",{split_policy:{},cases:[null]}, {...contract,cases:[{...contract.cases[0],evidence:{original:[0]}}]}, {...contract,cases:[{...contract.cases[0],evidence:{original:["2"]}}]}, {...contract,cases:[{...contract.cases[0],split:"training"}]}])assert.throws(()=>parseEvaluationImport(malformed));
assert.equal(parseEvaluationImport({name:"Own dataset",cases:[]}).kind,"dataset");
assert.throws(()=>parseEvaluationImport({name:"Missing cases"}));

const id="404d4ec6-fd1b-4995-a7d7-ba3f65a8405c";
assert.deepEqual(parseEvaluationDecision('{"approved":false}'),{approved:false});
assert.deepEqual(parseEvaluationDecision(JSON.stringify(JSON.stringify({approved:false}))),{approved:false});
assert.deepEqual(parseEvaluationDecision(JSON.stringify({approved:true,run_id:id})),{approved:true,run_id:id});
for(const value of [undefined,null,"invalid",{approved:"true",run_id:id},{approved:true},{approved:true,run_id:"javascript:alert(1)"}])assert.equal(parseEvaluationDecision(value),null);
console.log("Malformed imports are rejected before rendering; partitions/references and native saved approval/decline decisions retain their meaning.");
