import os
import json
import tomllib
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from openai import AsyncOpenAI
from dotenv import load_dotenv
import traceback

import llm_api.toolcalls as toolcalls
import llm_api.schema as schema

load_dotenv()

app = FastAPI()

app.add_middleware(
	CORSMiddleware,
	allow_origins=["http://localhost:5173"],
	allow_credentials=True,
	allow_methods=["*"],
	allow_headers=["*"],
)

with open("config.toml", "rb") as f:
	config = tomllib.load(f)

class ChatRequest(BaseModel):
	message: str
	endpoint_uri: str
	model_name: str
	system_prompt: str
	history: list[dict]

@app.get("/api/config")
async def get_config():
	return {
		"default_endpoint": config.get("default_endpoint", "https://openrouter.ai/api/v1"),
		"default_model": config.get("default_model", "inclusionai/ling-3.0-flash:free"),
		"default_system_prompt": config.get("default_system_prompt", "").strip(),
		"available_models": config.get("available_models", [])
	}

@app.post("/api/upload")
async def upload_instance(file: UploadFile = File(...)):
	if not file.filename.endswith('.json'):
		raise HTTPException(status_code=400, detail="Only JSON files are allowed.")

	content = await file.read()
	try:
		instance_data = json.loads(content)
		toolcalls.current_instance = instance_data
		return {"message": f"Successfully loaded {file.filename}", "instance": instance_data}
	except json.JSONDecodeError:
		raise HTTPException(status_code=400, detail="Invalid JSON file structure.")

@app.post("/api/chat")
async def chat_endpoint(request: ChatRequest):
	base_url = request.endpoint_uri
	if "localhost" in base_url or "127.0.0.1" in base_url:
		api_key = "lm-studio"
	elif "openrouter" in base_url:
		api_key = os.getenv("OPENROUTER_KEY")
	else:
		api_key = os.getenv("OPENAI_API_KEY")

	client = AsyncOpenAI(base_url=base_url, api_key=api_key)

	clean_history = []
	for msg in request.history:
		clean_msg = {
			"role": msg.get("role"),
			"content": msg.get("content", "")
		}
		if msg.get("tool_calls"):
			clean_msg["tool_calls"] = msg["tool_calls"]
		if msg.get("tool_call_id"):
			clean_msg["tool_call_id"] = msg["tool_call_id"]
		clean_history.append(clean_msg)

	async def stream_generator():
		messages = [{"role": "system", "content": request.system_prompt}] + clean_history
		messages.append({"role": "user", "content": request.message})

		while True:
			try:
				response = await client.chat.completions.create(
					model=request.model_name,
					messages=messages,
					tools=schema.openai_tools_schema
				)

				response_message = response.choices[0].message

				if response_message.tool_calls:
					assistant_msg = {
						"role": "assistant",
						"content": response_message.content or "",
						"tool_calls": [
							{
								"id": tc.id,
								"type": tc.type,
								"function": {
									"name": tc.function.name,
									"arguments": tc.function.arguments
								}
							} for tc in response_message.tool_calls
						]
					}
					messages.append(assistant_msg)

					yield json.dumps({"type": "message", "data": assistant_msg}) + "\n"

					for tool_call in response_message.tool_calls:
						func_name = tool_call.function.name
						try:
							args = json.loads(tool_call.function.arguments)
						except json.JSONDecodeError:
							args = {}

						if hasattr(toolcalls, func_name):
							func = getattr(toolcalls, func_name)
							result = func(**args)
						else:
							result = {"status": "error", "error": f"Unknown tool {func_name}"}

						tool_msg = {
							"role": "tool",
							"tool_call_id": tool_call.id,
							"name": func_name,
							"content": json.dumps(result)
						}
						messages.append(tool_msg)

						yield json.dumps({"type": "message", "data": tool_msg}) + "\n"
				else:
					reasoning = getattr(response_message, "reasoning_content", None)
					if not reasoning and hasattr(response_message, "model_extra") and response_message.model_extra:
						reasoning = response_message.model_extra.get("reasoning_content")

					final_msg = {
						"role": "assistant",
						"content": response_message.content or "",
						"reasoning": reasoning
					}

					#final response
					yield json.dumps({"type": "message", "data": final_msg}) + "\n"
					break

			except Exception as e:
				traceback.print_exc()
				yield json.dumps({"type": "error", "detail": str(e)}) + "\n"
				break

	return StreamingResponse(stream_generator(), media_type="application/x-ndjson")

if __name__ == "__main__":
	import uvicorn
	uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
