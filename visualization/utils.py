import json

def load_instance(filepath: str):
	with open(filepath, 'r', encoding='utf-8') as f:
		data = json.load(f)
		
	durations = {int(k): v for k, v in data["durations"].items()}
	predecessors = {int(k): v for k, v in data["predecessors"].items()}
	requests = {(req["job"], req["resource"]): req["amount"] for req in data["requests"]}
	
	return {
		"jobs": data["jobs"],
		"durations": durations,
		"predecessors": predecessors,
		"resources": data["resources"],
		"requests": requests,
		"shifts": data["shifts"],
		"orders": data["orders"]
	}