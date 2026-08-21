"""Cluster-side metric snapshots (plan §2.6).

A snapshot is taken at baseline / mid-run / final; deltas (rejections, GC) are
computed post - pre. Raw search-thread-pool `rejected` is monotonic since node
start, so only its delta during a test is a valid gate.
"""
import json


def snapshot(http):
    """http: a callable(method, path) -> (status, text). Returns a metrics dict
    (fields absent as None if the cluster didn't answer)."""
    out = {"cluster_status": None, "cpu_max_pct": None, "heap_max_pct": None,
           "search_active": None, "search_queue": None, "search_rejected": None,
           "old_gc_ms": None, "active_shards": None}

    s, body = http("GET", "/_cluster/health")
    if s == 200:
        try:
            h = json.loads(body)
            out["cluster_status"] = h.get("status")
            out["active_shards"] = h.get("active_shards")
        except Exception:  # noqa: BLE001
            pass

    s, body = http("GET", "/_nodes/stats/os,jvm,thread_pool"
                          "?filter_path=nodes.*.os.cpu.percent,"
                          "nodes.*.jvm.mem.heap_used_percent,"
                          "nodes.*.jvm.gc.collectors.old.collection_time_in_millis,"
                          "nodes.*.thread_pool.search")
    if s == 200:
        try:
            nodes = json.loads(body).get("nodes", {}).values()
            cpu, heap, gc, active, queue, rej = [], [], 0, 0, 0, 0
            for n in nodes:
                cpu.append(n.get("os", {}).get("cpu", {}).get("percent", 0))
                heap.append(n.get("jvm", {}).get("mem", {}).get("heap_used_percent", 0))
                gc += (n.get("jvm", {}).get("gc", {}).get("collectors", {})
                        .get("old", {}).get("collection_time_in_millis", 0))
                sp = n.get("thread_pool", {}).get("search", {})
                active += sp.get("active", 0)
                queue += sp.get("queue", 0)
                rej += sp.get("rejected", 0)
            out.update(cpu_max_pct=max(cpu) if cpu else None,
                       heap_max_pct=max(heap) if heap else None,
                       old_gc_ms=gc, search_active=active,
                       search_queue=queue, search_rejected=rej)
        except Exception:  # noqa: BLE001
            pass
    return out


def delta(pre, post):
    """post - pre for the monotonic counters that gate on change."""
    def d(k):
        a, b = pre.get(k), post.get(k)
        return None if a is None or b is None else b - a
    return {"search_rejected_delta": d("search_rejected"), "old_gc_ms_delta": d("old_gc_ms")}
