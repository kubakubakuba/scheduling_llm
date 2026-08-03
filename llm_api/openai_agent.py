import json
import os
import sys
from dotenv import load_dotenv
from openai import OpenAI
import toolcalls

load_dotenv()

############### client and model selection

#client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
#client = OpenAI(base_url="http://localhost:1234/v1", api_key="lm-studio")
#client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=os.getenv("OPENROUTER_KEY"))

client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=os.getenv("OPENROUTER_KEY"))
#client = OpenAI(base_url="http://localhost:1234/v1", api_key="lm-studio")

model_name = "inclusionai/ling-3.0-flash:free" #'gpt-4o' for openai models or "inclusionai/ling-3.0-flash:free" for OpenRouter or "local-model" for LMS
#model_name = "google/gemma-4-12b-qat"

###############

toolcalls.load_instance("./instance.json")

system_instruction = (
	"You are an assistant managing a CP Optimizer instance."
	"Prefer using edit_json_in_place for minor changes to specific values."
	"Use propose_updated_instance ONLY for large structural changes. Do NOT use it when you can easily edit a singular number."
	"Use run_solver when requested to evaluate or solve the current instance.\n\n"
	f"Current state:\n```json\n{json.dumps(toolcalls.get_current_instance())}\n```"
)

prompt = (
	"First solve the given instance of this optimization problem with the given solver and obtain its objective."
	"Job 6 now precedes job 30, change the precedences, so it satisfies this condition."
	"After modifying it, run the solver to check the new weighted tardiness objective and compare it with the original value."
	"Print out a nice summary of what has been done, with a table listing all the changes made to the json instance file. Explain why did the change in the objective happen and which job is causing it (contributes most to it)."
)

messages = [
	{"role": "system", "content": system_instruction},
	{"role": "user", "content": prompt}
]

print("Sending initial request")

while True:
	response = client.chat.completions.create(
		model=model_name,
		messages=messages,
		tools=toolcalls.openai_tools_schema
	)
	
	response_message = response.choices[0].message
	
	if response_message.tool_calls:
		messages.append(response_message)
		
		for tool_call in response_message.tool_calls:
			function_name = tool_call.function.name
			
			try:
				function_args = json.loads(tool_call.function.arguments)
			except json.JSONDecodeError:
				function_args = {}
				
			if hasattr(toolcalls, function_name):
				func = getattr(toolcalls, function_name)
				result = func(**function_args)
			else:
				result = {"status": "error", "error": f"Unknown function {function_name}"}
				
			messages.append({
				"role": "tool",
				"tool_call_id": tool_call.id,
				"content": json.dumps(result)
			})
			
	else:
		print("\n--- Final Model Output ---")
		print(response_message.content)
		break