import jsonschema

MRCPSP_SCHEMA = {
	"type": "object",
	"properties": {
		"instance_name": {"type": "string"},
		"jobs": {
			"type": "array",
			"items": {"type": "integer"}
		},
		"durations": {
			"type": "object",
			"patternProperties": {
				"^[0-9]+$": {"type": "integer", "minimum": 0}
			}
		},
		"predecessors": {
			"type": "object",
			"patternProperties": {
				"^[0-9]+$": {
					"type": "array",
					"items": {"type": "integer"}
				}
			}
		},
		"resources": {
			"type": "array",
			"items": {"type": "string"}
		},
		"requests": {
			"type": "array",
			"items": {
				"type": "object",
				"properties": {
					"job": {"type": "integer"},
					"resource": {"type": "string"},
					"amount": {"type": "integer", "minimum": 1}
				},
				"required": ["job", "resource", "amount"]
			}
		},
		"shifts": {
			"type": "object",
			"patternProperties": {
				"^.*$": {
					"type": "array",
					"items": {
						"type": "array",
						"items": {"type": "integer"},
						"minItems": 3,
						"maxItems": 3
					}
				}
			}
		},
		"orders": {
			"type": "array",
			"items": {
				"type": "object",
				"properties": {
					"sink_job": {"type": "integer"},
					"due_date": {"type": "integer"},
					"weight": {"type": "number"}
				},
				"required": ["sink_job", "due_date", "weight"]
			}
		}
	},
	"required": [
		"instance_name", "jobs", "durations", "predecessors", 
		"resources", "requests", "shifts", "orders"
	]
}

def validate_instance(instance_data: dict) -> None:
	jsonschema.validate(instance=instance_data, schema=MRCPSP_SCHEMA)
