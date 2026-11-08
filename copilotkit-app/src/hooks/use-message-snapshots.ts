"use client";
import {useEffect} from "react";
import type {AbstractAgent} from "@copilotkit/react-core/v2";
import {orderMessageSnapshot} from "@/lib/message-snapshot";

export function useMessageSnapshots(agent:AbstractAgent){
  useEffect(()=>{
    let active:string|null=null;
    const subscription=agent.subscribe({
      onRunInitialized:({input})=>{active=input.runId;},
      onRunFinalized:({input})=>{if(active===input.runId)active=null;},
      onMessagesSnapshotEvent:({input,event,messages})=>{
        if(active&&active!==input.runId)return;
        const submitted=input.messages.findLast(item=>item.role==="user");
        if(submitted&&!event.messages.some(item=>item.id===submitted.id))return;
        return {messages:orderMessageSnapshot(messages,event.messages)};
      },
    });
    return()=>subscription.unsubscribe();
  },[agent]);
}
