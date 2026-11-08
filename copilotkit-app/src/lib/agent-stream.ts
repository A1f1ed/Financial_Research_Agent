import {Middleware,type AbstractAgent,type BaseEvent,type RunAgentInput} from "@ag-ui/client";
import {Observable} from "rxjs";
import {coalesceAgentStream} from "./agent-stream-events";

export class ResearchStreamMiddleware extends Middleware{
  run(input:RunAgentInput,next:AbstractAgent):Observable<BaseEvent>{
    return coalesceAgentStream(this.runNext(input,next),150,counts=>{
      // Content-free diagnostics: never log prompts, arguments or source text.
      console.info("[AG-UI stream]",JSON.stringify(counts));
    });
  }
}
