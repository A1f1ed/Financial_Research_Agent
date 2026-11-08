import {z} from "zod";

const legacyCase=z.object({
  id:z.string().min(1).max(80).regex(/^[a-zA-Z0-9_-]+$/),
  question:z.string().min(2).max(500),category:z.enum(["financial","boundary","vision","wiki","relations"]),
  split:z.enum(["development","acceptance"]),
  evidence:z.record(z.string().min(1).max(160),z.array(z.number().int().min(1).max(2000)).max(2000)).default({}),
}).passthrough();
const legacyContract=z.object({
  version:z.string().min(1).max(100),split_policy:z.record(z.unknown()),
  default_scope:z.object({as_of:z.string().min(10).max(40)}).passthrough(),cases:z.array(legacyCase).min(1).max(100),
}).passthrough();
export type SourceContract=z.infer<typeof legacyContract>;

export function parseEvaluationImport(value:unknown):{kind:"legacy";payload:SourceContract}|{kind:"dataset";payload:Record<string,unknown>}{
  if(!value||typeof value!=="object"||Array.isArray(value))throw new Error("Import must be a JSON object.");
  if("split_policy" in value){
    const parsed=legacyContract.safeParse(value);
    if(!parsed.success){const issue=parsed.error.issues[0];throw new Error(`Invalid source contract (${issue.path.join(".")}): ${issue.message}`);}
    return {kind:"legacy",payload:parsed.data};
  }
  const parsed=z.object({name:z.string().trim().min(1).max(120),cases:z.array(z.unknown()).max(100)}).passthrough().safeParse(value);
  if(!parsed.success)throw new Error("Dataset JSON needs a name and a cases array.");
  return {kind:"dataset",payload:parsed.data};
}
