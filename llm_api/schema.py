import sys, os
sys.path.append(os.path.abspath(".."))

MRCPSP_SCHEMA = {
	"$schema": "https://json-schema.org/draft/2020-12/schema",
	"type": "object",
	"additionalProperties": False,
	"properties": {
		"instance_name": {"type": "string"},
		"jobs": {
			"type": "array",
			"items": {"type": "integer", "minimum": 0},
			"uniqueItems": True
		},
		"durations": {
			"type": "object",
			"additionalProperties": False,
			"patternProperties": {
				"^[0-9]+$": {"type": "integer", "minimum": 0}
			}
		},
		"predecessors": {
			"type": "object",
			"additionalProperties": False,
			"patternProperties": {
				"^[0-9]+$": {
					"type": "array",
					"items": {"type": "integer", "minimum": 0},
					"uniqueItems": True
				}
			}
		},
		"resources": {
			"type": "array",
			"items": {"type": "string", "minLength": 1},
			"uniqueItems": True
		},
		"requests": {
			"type": "array",
			"items": {
				"type": "object",
				"additionalProperties": False,
				"properties": {
					"job": {"type": "integer", "minimum": 0},
					"resource": {"type": "string", "minLength": 1},
					"amount": {"type": "integer", "minimum": 1}
				},
				"required": ["job", "resource", "amount"]
			}
		},
		"shifts": {
			"type": "object",
			"additionalProperties": False,
			"patternProperties": {
				"^.*$": {
					"type": "array",
					"items": {
						"type": "array",
						"items": {"type": "integer", "minimum": 0},
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
				"additionalProperties": False,
				"properties": {
					"sink_job": {"type": "integer", "minimum": 0},
					"due_date": {"type": "integer", "minimum": 0},
					"weight": {"type": "number", "minimum": 0}
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


openai_tools_schema = [
	{
		"type": "function",
		"function": {
			"name": "query_instance_data",
			"description": "Query specific parts of the loaded JSON instance using dot notation.",
			"strict": True,
			"parameters": {
				"type": "object",
				"properties": {
					"paths": {
						"type": "array",
						"items": {
							"type": "string"
						},
						"description": "List of dot-separated paths to retrieve. Example: ['orders', 'durations.22', 'shifts.R1']"
					}
				},
				"required": ["paths"],
				"additionalProperties": False
			}
		}
	},
	{
		"type": "function",
		"function": {
			"name": "edit_json_in_place",
			"description": "Edit a specific scalar value. Use ONLY dot notation for arrays (e.g., 'orders.0.due_date'). DO NOT use brackets like 'orders[0]'.",
			"strict": True,
			"parameters": {
				"type": "object",
				"properties": {
					"path": {
						"type": "string",
						"description": "Dot-separated path. Example: 'durations.22' or 'orders.5.due_date'. No brackets allowed."
					},
					"new_value": {
						"type": "number",
						"description": "The new numerical value to set."
					}
				},
				"required": ["path", "new_value"],
				"additionalProperties": False
			}
		}
	},
	{
		"type": "function",
		"function": {
			"name": "propose_updated_instance",
			"description": "Propose a completely updated Modified-RCPSP problem instance.",
			"strict": True,
			"parameters": {
				"type": "object",
				"properties": {
					"updated_instance": {
						"type": "object",
						"description": "The full JSON object representing the modified problem."
					}
				},
				"required": ["updated_instance"],
				"additionalProperties": False
			}
		}
	},
	{
		"type": "function",
		"function": {
			"name": "run_solver",
			"description": "Run the CP Optimizer solver on the current problem instance state.",
			"strict": True,
			"parameters": {
				"type": "object",
				"properties": {
					"time_limit": {
						"type": "integer",
						"description": "Maximum solver run time in seconds."
					}
				},
				"required": ["time_limit"],
				"additionalProperties": False
			}
		}
	},
	{
		"type": "function",
		"function": {
			"name": "visualize_schedule",
			"description": "Generate visualization data for the current solved schedule (Gantt chart timeline).",
			"strict": True,
			"parameters": {
				"type": "object",
				"properties": {},
				"required": [],
				"additionalProperties": False
			}
		}
	},
	{
		"type": "function",
		"function": {
			"name": "set_order_due_date",
			"description": "Change the due date of an existing order.",
			"strict": True,
			"parameters": {
				"type": "object",
				"properties": {
					"sink_job": {"type": "integer"},
					"due_date": {"type": "integer"}
				},
				"required": ["sink_job", "due_date"],
				"additionalProperties": False
			}
		}
	},
	{
		"type": "function",
		"function": {
			"name": "set_job_duration",
			"description": (
				"Change the duration of one existing job. "
				"This operation does not change its precedences or resource demands."
			),
			"strict": True,
			"parameters": {
				"type": "object",
				"properties": {
					"job": {
						"type": "integer",
						"minimum": 0,
						"description": "ID of the existing job."
					},
					"duration": {
						"type": "integer",
						"minimum": 0,
						"description": "New non-negative duration of the job."
					}
				},
				"required": ["job", "duration"],
				"additionalProperties": False
			}
		}
	},
	{
		"type": "function",
		"function": {
			"name": "set_resource_capacity",
			"description": (
				"Change the capacity of an existing resource-calendar interval. "
				"The interval must already exist exactly in the calendar. "
				"Intervals are half-open: [start, end). "
				"This operation does not split or create intervals."
			),
			"strict": True,
			"parameters": {
				"type": "object",
				"properties": {
					"resource": {
						"type": "string",
						"description": "ID of the existing resource."
					},
					"start": {
						"type": "integer",
						"minimum": 0,
						"description": "Start of the existing interval."
					},
					"end": {
						"type": "integer",
						"minimum": 0,
						"description": "End of the existing interval."
					},
					"capacity": {
						"type": "integer",
						"minimum": 0,
						"description": "New non-negative capacity."
					}
				},
				"required": [
					"resource",
					"start",
					"end",
					"capacity"
				],
				"additionalProperties": False
			}
		}
	},
	{
		"type": "function",
		"function": {
			"name": "add_precedence_constraint",
			"description": (
				"Add a precedence constraint requiring the first job "
				"to finish before the second job starts. "
				"The operation is rejected if it would create a cycle."
			),
			"strict": True,
			"parameters": {
				"type": "object",
				"properties": {
					"before": {
						"type": "integer",
						"minimum": 0,
						"description": (
							"Job that must finish before the other job starts."
						)
					},
					"after": {
						"type": "integer",
						"minimum": 0,
						"description": (
							"Job that may start only after the first job finishes."
						)
					}
				},
				"required": ["before", "after"],
				"additionalProperties": False
			}
		}
	},
	{
		"type": "function",
		"function": {
			"name": "remove_precedence_constraint",
			"description": (
				"Remove an existing precedence constraint requiring "
				"the first job to finish before the second job starts."
			),
			"strict": True,
			"parameters": {
				"type": "object",
				"properties": {
					"before": {
						"type": "integer",
						"minimum": 0,
						"description": "Previously preceding job."
					},
					"after": {
						"type": "integer",
						"minimum": 0,
						"description": "Previously succeeding job."
					}
				},
				"required": ["before", "after"],
				"additionalProperties": False
			}
		}
	}
]
