import { useEffect, useState } from "react";
import { researchRequest } from "@/components/workbench-panels";
import { errorText, useDocumentCopy } from "@/components/documents/shared";

export type Collection = {
  id: string; name: string; description: string; symbols: string[]; topics: string[]; revision: number;
  archived: boolean; created_at: string; updated_at: string; version_policy: string;
  material_revision?: string;
  coverage: { documents: number; active_documents: number; archived_documents: number; removed_documents: number;
    pages: number; text_pages: number; needs_vision_pages: number; failed_pages: number; pending_pages: number;
    references: number; semantic_index: string };
};

export function useKnowledgeResource<T>(path: string | null, revision: number, pollMs=10000) {
  const c = useDocumentCopy();
  const [state, setState] = useState<{ path: string | null; data: T | null; error: string; loading: boolean }>({ path: null, data: null, error: "", loading: true });
  useEffect(() => {
    if (!path) return;
    const controller = new AbortController(); let timer: ReturnType<typeof setTimeout>; let pending = false;
    setState(previous => ({ path, data: previous.path === path ? previous.data : null, loading: true, error: "" }));
    const load = async (initial = false) => {
      if (pending || controller.signal.aborted || document.hidden && !initial) return;
      pending = true; clearTimeout(timer);
      try {
        const data = await researchRequest<T>(path, "GET", undefined, controller.signal);
        if (!controller.signal.aborted) setState({ path, data, error: "", loading: false });
      } catch (err) { if (!controller.signal.aborted) setState(previous => ({ ...previous, error: errorText(err, c), loading: false })); }
      finally { pending = false; if (!controller.signal.aborted && !document.hidden && pollMs>0) timer = setTimeout(() => void load(), pollMs); }
    };
    const visibility = () => { if (document.hidden) clearTimeout(timer); else void load(); };
    document.addEventListener("visibilitychange", visibility); void load(true);
    return () => { controller.abort(); clearTimeout(timer); document.removeEventListener("visibilitychange", visibility); };
  }, [path, revision, c, pollMs]);
  return state.path === path ? state : { path, data: null, error: "", loading: true };
}
