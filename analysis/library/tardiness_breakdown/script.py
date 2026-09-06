def analyze(context, parameters):
    instance, schedule = context["instance"], context.get("schedule") or {}
    rows = []
    total = 0
    for order in instance["orders"]:
        end = schedule.get(str(order["sink_job"]), schedule.get(order["sink_job"], [0, 0]))[1]
        tardiness = max(0, end - order["due_date"])
        contribution = order["weight"] * tardiness
        total += contribution
        rows.append({"sink_job": order["sink_job"], "end": end, "due_date": order["due_date"], "tardiness": tardiness, "weighted_contribution": contribution})
    return {"status": "success", "total_weighted_tardiness": total, "orders": rows}
