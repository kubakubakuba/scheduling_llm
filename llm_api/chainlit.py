import json
import os
import tomllib
from dotenv import load_dotenv
import chainlit as cl
from chainlit.input_widget import TextInput
from openai import AsyncOpenAI
import toolcalls

load_dotenv()

with open("config.toml", "rb") as f:
    config = tomllib.load(f)

@cl.on_chat_start
async def start():
    settings = await cl.ChatSettings(
        [
            TextInput(
                id="EndpointURI",
                label="API Endpoint URI",
                initial=config.get("default_endpoint", "https://openrouter.ai/api/v1"),
            ),
            TextInput(
                id="ModelName",
                label="Model Name",
                initial=config.get("default_model", "poolside/laguna-s-2.1:free"),
            ),
            TextInput(
                id="SystemPrompt",
                label="System Prompt",
                initial=config.get("default_system_prompt", "").strip(),
                multiline=True
            )
        ]
    ).send()

    cl.user_session.set("settings_dict", {
        "EndpointURI": config.get("default_endpoint", "https://openrouter.ai/api/v1"),
        "ModelName": config.get("default_model", "poolside/laguna-s-2.1:free"),
        "SystemPrompt": config.get("default_system_prompt", "").strip()
    })

    cl.user_session.set("instance_loaded", False)

    await cl.Message(
        content="Welcome. Configure the LLM endpoint and prompt in the settings panel.\n\n"
                "Upload an MRCPSP JSON instance file to begin."
    ).send()

@cl.on_settings_update
async def setup_agent(new_settings):
    cl.user_session.set("settings_dict", new_settings)

    messages = cl.user_session.get("messages")
    if messages and messages[0]["role"] == "system":
        if cl.user_session.get("instance_loaded"):
            current_state_str = json.dumps(toolcalls.current_instance, indent=2)
            updated_prompt = new_settings["SystemPrompt"]

            messages[0]["content"] = (
                f"{updated_prompt}\n\nCurrent state:\n```json\n{current_state_str}\n```"
            )

    await cl.Message(content="Settings updated.").send()

@cl.on_message
async def main(message: cl.Message):
    instance_loaded = cl.user_session.get("instance_loaded")
    settings = cl.user_session.get("settings_dict")

    if not instance_loaded:
        json_files = [
            file for file in message.elements
            if file.mime == "application/json" or file.name.endswith(".json")
        ]

        if not json_files:
            await cl.Message(content="Please upload a valid JSON instance file first.").send()
            return

        uploaded_file = json_files[0]
        with open(uploaded_file.path, "r") as f:
            instance_data = json.load(f)

        toolcalls.current_instance = instance_data
        cl.user_session.set("instance_loaded", True)

        current_state_str = json.dumps(instance_data, indent=2)
        system_prompt = settings["SystemPrompt"]
        full_system_instruction = (
            f"{system_prompt}\n\nCurrent state:\n```json\n{current_state_str}\n```"
        )

        cl.user_session.set(
            "messages", [{"role": "system", "content": full_system_instruction}]
        )

        await cl.Message(
            content=f"Successfully loaded instance **{uploaded_file.name}**."
        ).send()
        return

    base_url = settings["EndpointURI"]
    model_name = settings["ModelName"]

    if "localhost" in base_url or "127.0.0.1" in base_url:
        api_key = "lm-studio"
    elif "openrouter" in base_url:
        api_key = os.getenv("OPENROUTER_KEY")
    else:
        api_key = os.getenv("OPENAI_API_KEY")

    client = AsyncOpenAI(base_url=base_url, api_key=api_key)

    messages = cl.user_session.get("messages")
    messages.append({"role": "user", "content": message.content})

    while True:
        response = await client.chat.completions.create(
            model=model_name, messages=messages, tools=toolcalls.openai_tools_schema
        )

        response_message = response.choices[0].message

        if response_message.tool_calls:
            messages.append(response_message)

            for tool_call in response_message.tool_calls:
                func_name = tool_call.function.name
                try:
                    args = json.loads(tool_call.function.arguments)
                except json.JSONDecodeError:
                    args = {}

                async with cl.Step(name=func_name) as step:
                    step.input = args

                    if hasattr(toolcalls, func_name):
                        func = getattr(toolcalls, func_name)
                        result = func(**args)
                    else:
                        result = {"status": "error", "error": f"Unknown tool {func_name}"}

                    step.output = result

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(result),
                    }
                )
        else:
            final_text = response_message.content
            messages.append({"role": "assistant", "content": final_text})
            await cl.Message(content=final_text).send()
            break
