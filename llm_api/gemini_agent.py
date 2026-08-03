import json
import os
from dotenv import load_dotenv
from google import genai
import toolcalls

load_dotenv()
client = genai.Client(api_key=os.getenv("GEMINI_KEY"))

toolcalls.load_instance("../data/jsons/j3010_5.json")

chat = client.chats.create(
	model="gemini-3.5-flash-lite",
	config={
		"tools": [
			toolcalls.edit_json_in_place, 
			toolcalls.propose_updated_instance, 
			toolcalls.run_solver
		],
		"system_instruction": (
			"You are an assistant managing a CP Optimizer instance. "
			"Prefer using edit_json_in_place for minor changes to specific values. "
			"Use propose_updated_instance only for large structural changes. "
			"Use run_solver when requested to evaluate or solve the current instance.\n\n"
			f"Current state:\n```json\n{json.dumps(toolcalls.get_current_instance())}\n```"
		),
	},
)

prompt = (
	"First solve the given instance of this optimization problem with the given solver and obtain its objective."
	"Change the due dates of all sink jobs 5 units to the future (for each sink job)."
	"After modifying it, run the solver to check the new weighted tardiness objective and compare it with the original value."
)

response = chat.send_message(prompt)

print("\n--- Final Model Output ---")
print(response.text)

print("\n--- Conversation History ---")
for message in chat.get_history():
	print(f"\nRole: {message.role}")
	if message.parts:
		for part in message.parts:
			if part.function_call:
				print(f"  [Function Call Requested] {part.function_call.name}")
				print(f"  [Arguments] {part.function_call.args}")
			elif part.function_response:
				print(f"  [Function Result Received] {part.function_response.name}")
			elif part.text:
				text_preview = part.text.replace('\n', ' ')
				if len(text_preview) > 100:
					text_preview = text_preview[:100] + "..."
				print(f"  [Text] {text_preview}")