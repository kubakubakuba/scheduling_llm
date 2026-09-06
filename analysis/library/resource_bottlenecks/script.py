def analyze(context, parameters):
    instance, schedule = context["instance"], context.get("schedule") or {}
    requests = {(r["job"], r["resource"]): r["amount"] for r in instance["requests"]}
    result = {}
    for resource in instance["resources"]:
        capacities = {t: cap for start, end, cap in instance["shifts"].get(resource, []) for t in range(start, end)}
        usage = {t: sum(requests.get((int(job), resource), 0) for job, interval in schedule.items() if interval[0] <= t < interval[1]) for t in capacities}
        peak = max(usage.values(), default=0)
        saturated = [t for t, value in usage.items() if value >= capacities.get(t, 0) and value > 0]
        result[resource] = {"peak_usage": peak, "peak_capacity": max(capacities.values(), default=0), "saturated_ticks": saturated}
    return {"status": "success", "resources": result}
