import { api } from "./api.js";

// Runs a sync as a sequence of small batches so no single request risks the 60s
// serverless limit, and reports progress as it goes. clientId=null = sync everyone
// (deduped); a clientId scopes it to one client. onProgress({done, total, phase}).
const BATCH = 30; // profiles queued per request — smooth progress; the server is also time-guarded

export async function runSync({ clientId = null, onProgress } = {}) {
  const { profiles, total } = await api.syncPlan(clientId);
  onProgress?.({ done: 0, total, phase: total ? "firing" : "empty" });
  if (!total) return { total: 0 };

  let done = 0;
  let queue = profiles;
  while (queue.length) {
    const batch = queue.slice(0, BATCH);
    let res;
    try {
      res = await api.syncFire(batch);
    } catch (e) {
      // Surface but don't abort the whole run on one flaky batch — retry the rest.
      onProgress?.({ done, total, phase: "error", error: e.message });
      throw e;
    }
    const remaining = res.remaining || [];
    done += batch.length - remaining.length;
    queue = [...remaining, ...queue.slice(BATCH)];
    onProgress?.({ done, total, phase: "firing" });
  }
  onProgress?.({ done: total, total, phase: "done" });
  return { total };
}
