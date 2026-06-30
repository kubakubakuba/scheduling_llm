import json
import problem_instance
from problem_instance import ProblemInstance

problem_instance.get_file = lambda filepath: filepath

def convert_psplib_to_json(filepath):
    pi = ProblemInstance(filepath)

    json_data = {
        "metadata": {
            "project_count": pi.project_count,
            "jobs_count": pi.jobs,
            "horizon": pi.horizon
        },
        "resources": {
            "renewable": pi.renewable_resources,
            "availabilities": pi.resource_availabilities,
            "shift_modes": pi.resource_shift_modes
        },
        "jobs": [],
        "orders": []
    }

    for i in range(pi.jobs):
        req = pi.requests_and_durations[i]
        prec = pi.precedence_relations[i]

        job_data = {
            "id": i,
            "duration": req.duration,
            "resource_requests": req.renewable_requests,
                0,
                0
            ],
            "successors": [
                2,
            "successors": prec.successors
        }
        json_data["jobs"].append(job_data)

    if pi.component_order:
        for idx, node in enumerate(pi.component_order):
            order_data = {
                "component_id": idx,
                "sink_node": node,
                "weight": pi.component_weights[idx] if pi.component_weights else 0,
                "due_date": pi.due_dates[node] if pi.due_dates else 0
            }
            json_data["orders"].append(order_data)

    out_name = filepath.split('/')[-1].replace('.txt', '') + '.json'

    with open(out_name, "w") as f:
        json.dump(json_data, f, indent=4)

    print(f"Successfully converted {filepath} to {out_name}")

if __name__ == "__main__":
    convert_psplib_to_json("j301_3.sm.txt")
