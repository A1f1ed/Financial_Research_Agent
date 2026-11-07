/** DOM textareas normalize CR/CRLF and count UTF-16 units. Python offsets
 * count original Unicode code points. Never apply DOM offsets to raw text. */
export function evidenceSelection(text:string,start:number,end:number){
  const points=Array.from(text);const boundaries=new Map<number,number>([[0,0]]);let units=0;
  for(let index=0;index<points.length;){
    const point=points[index];
    if(point==="\r"&&points[index+1]==="\n"){index+=2;units+=1;}
    else{index+=1;units+=point.length;}
    boundaries.set(units,index);
  }
  const from=boundaries.get(start),to=boundaries.get(end);
  if(from===undefined||to===undefined||to<=from)return null;
  return {start_offset:from,end_offset:to,quote:points.slice(from,to).join("")};
}
