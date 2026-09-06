def analyze(context, parameters):
    instance = context["instance"]
    durations = {int(k): int(v) for k, v in instance["durations"].items()}
    predecessors = {int(k): [int(x) for x in v] for k, v in instance["predecessors"].items()}
    best = {}
    path = {}
    for job in instance["jobs"]:
        preds = predecessors.get(int(job), [])
        if not preds:
            best[job], path[job] = durations[job], [job]
        else:
            parent = max(preds, key=lambda item: best.get(item, 0))
            best[job], path[job] = best[parent] + durations[job], path[parent] + [job]
    sink = max(best, key=best.get)
    critical = path[sink]
    return {"status": "success", "critical_path": critical, "duration": best[sink], "sink": sink,
            "visualizations": [{"type": "bar", "title": "Critical path durations", "labels": [str(job) for job in critical], "values": [durations[job] for job in critical]}]}
