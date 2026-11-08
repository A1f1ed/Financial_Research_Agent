import type {Message} from "@ag-ui/core";

/** A backend snapshot owns canonical conversation order. Keep native reasoning
 * and activity cards alongside their turn instead of appending recovered old
 * assistant messages after the latest answer (the default merge is additive).
 */
export function orderMessageSnapshot(current:readonly Message[],snapshot:readonly Message[]):Message[]{
  const ids=new Set(snapshot.map(item=>item.id));const existing=new Map(current.map(item=>[item.id,item]));
  const before=new Map<string,Message[]>();const unanchored:Message[]=[];
  let userId:string|undefined;
  for(let index=0;index<current.length;index++){
    const item=current[index];if(item.role==="user")userId=item.id;
    if(ids.has(item.id)||!["reasoning","activity"].includes(item.role))continue;
    let anchor:string|undefined;
    for(let next=index+1;next<current.length;next++){
      if(current[next].role==="user")break;
      if(current[next].role==="assistant"&&ids.has(current[next].id)){anchor=current[next].id;break;}
    }
    if(!anchor){
      const start=userId?snapshot.findIndex(message=>message.id===userId):snapshot.findIndex(message=>message.role==="user");
      if(start>=0)for(let next=start+1;next<snapshot.length&&snapshot[next].role!=="user";next++)if(snapshot[next].role==="assistant")anchor=snapshot[next].id;
    }
    if(anchor)before.set(anchor,[...(before.get(anchor)||[]),item]);else unanchored.push(item);
  }
  return [...unanchored,...snapshot.flatMap(item=>[...(before.get(item.id)||[]),{...existing.get(item.id),...item} as Message])];
}
