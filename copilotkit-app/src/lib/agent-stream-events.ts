import type {BaseEvent} from "@ag-ui/core";
import {Observable} from "rxjs";

type DeltaEvent=BaseEvent&{delta:string;messageId?:string;toolCallId?:string};
export type StreamCounts={input:number;output:number;duplicateTokenDebug:number};
const DELTAS=new Set(["TEXT_MESSAGE_CONTENT","REASONING_MESSAGE_CONTENT","THINKING_TEXT_MESSAGE_CONTENT","TOOL_CALL_ARGS"]);

/** Batch adjacent token fragments before Intelligence assigns durable event IDs.
 * Lifecycle/tool/state boundaries are never delayed behind another event.
 * Keep native text/reasoning/arguments and all tool/lifecycle debug records.
 */
export function coalesceAgentStream(source:Observable<BaseEvent>,intervalMs=150,onCounts?:(value:StreamCounts)=>void){
  return new Observable<BaseEvent>(subscriber=>{
    let pending:DeltaEvent|null=null;let timer:ReturnType<typeof setTimeout>|null=null;let representedToken=false;
    const counts:StreamCounts={input:0,output:0,duplicateTokenDebug:0};
    const emit=(event:BaseEvent)=>{counts.output++;subscriber.next(event);};
    const flush=()=>{if(timer!==null){clearTimeout(timer);timer=null;}if(pending){const event=pending;pending=null;emit(event);}};
    const subscription=source.subscribe({next(event){
      counts.input++;
      const raw=event as BaseEvent&{event?:{event?:string}};
      if(event.type==="RAW"&&raw.event?.event==="on_chat_model_stream"&&representedToken){
        counts.duplicateTokenDebug++;representedToken=false;return;
      }
      const candidate=event as DeltaEvent;
      representedToken=DELTAS.has(event.type)&&typeof candidate.delta==="string";
      if(!representedToken){flush();emit(event);return;}
      if(pending&&(pending.type!==candidate.type||pending.messageId!==candidate.messageId||pending.toolCallId!==candidate.toolCallId))flush();
      pending=pending?{...pending,delta:pending.delta+candidate.delta}:{...candidate};
      if(pending.delta.length>=4096)flush();
      else if(timer===null)timer=setTimeout(flush,intervalMs);
    },error(error){flush();onCounts?.({...counts});subscriber.error(error);},complete(){flush();onCounts?.({...counts});subscriber.complete();}});
    return()=>{if(timer!==null)clearTimeout(timer);pending=null;subscription.unsubscribe();};
  });
}
