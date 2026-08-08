import json
import os
import streamlit as st
from openai import OpenAI
import toolcalls
from dotenv import load_dotenv

load_dotenv()

st.set_page_config(page_title="MRCPSP Agent Workstation", layout="wide")

if "messages" not in st.session_state:
    st.session_state.messages = []

if "instance_loaded" not in st.session_state:
    toolcalls.load_instance("../data/jsons/j302_5.json")
    st.session_state.instance_loaded = True

with st.sidebar:
    st.header("Agent Configuration")

    st.subheader("Problem Instance")

    data_dir = os.path.abspath("../data/jsons")
    try:
        available_files = [f for f in os.listdir(data_dir) if f.endswith(".json")]
        available_files.sort()
    except FileNotFoundError:
        available_files = []
        st.error(f"Data directory not found at {data_dir}")

    if available_files:
        selected_file = st.selectbox(
            "Select JSON Instance:",
            options=available_files,
            index=available_files.index(st.session_state.get("current_filename", available_files[0])) if "current_filename" in st.session_state else 0
        )

        if selected_file != st.session_state.get("current_filename"):
            st.session_state.current_filename = selected_file
            toolcalls.load_instance(os.path.join(data_dir, selected_file))
            st.session_state.messages = []
            st.rerun()
    else:
        st.warning("No JSON files found in ../data/jsons")

    st.divider()

    provider = st.selectbox(
        "API Provider",
        ["OpenRouter", "LM Studio (Local)", "OpenAI Direct"]
    )

    if provider == "OpenRouter":
        base_url = "https://openrouter.ai/api/v1"
        api_key = os.getenv("OPENROUTER_KEY", "")
        default_model = "inclusionai/ling-3.0-flash:free"
    elif provider == "LM Studio (Local)":
        base_url = "http://localhost:1234/v1"
        api_key = "lm-studio"
        default_model = "local-model"
    else:
        base_url = None
        api_key = os.getenv("OPENAI_API_KEY", "")
        default_model = "gpt-4o"

    model_name = st.text_input("Model Identifier", value=default_model)

    st.divider()

    st.subheader("System Prompt")
    default_system_prompt = (
        "You are an assistant managing a CP Optimizer instance.\n"
        "Prefer using edit_json_in_place for minor changes to specific values.\n"
        "Use propose_updated_instance only for large structural changes.\n"
        "Use run_solver when requested to evaluate or solve the current instance."
    )
    system_prompt_input = st.text_area("Edit System Instruction", value=default_system_prompt, height=150)

    st.divider()

    st.subheader("Active Tools")
    with st.expander("View Active Tool Schemas"):
        st.json(toolcalls.openai_tools_schema)

    if st.button("Clear Chat History"):
        st.session_state.messages = []
        st.rerun()

st.title("MRCPSP Optimization Agent Workstation")

current_state_str = json.dumps(toolcalls.get_current_instance(), indent=2)
full_system_instruction = f"{system_prompt_input}\n\nCurrent state:\n```json\n{current_state_str}\n```"

for msg in st.session_state.messages:
    if msg["role"] in ["user", "assistant"]:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

if prompt := st.chat_input("Ask the agent to solve or modify the problem instance..."):
    st.chat_message("user").markdown(prompt)
    st.session_state.messages.append({"role": "user", "content": prompt})

    api_messages = [{"role": "system", "content": full_system_instruction}]
    for m in st.session_state.messages:
        api_messages.append({"role": m["role"], "content": m["content"]})

    client = OpenAI(base_url=base_url, api_key=api_key)

    with st.chat_message("assistant"):
        response_placeholder = st.empty()

        while True:
            response = client.chat.completions.create(
                model=model_name,
                messages=api_messages,
                tools=toolcalls.openai_tools_schema
            )

            response_message = response.choices[0].message

            if response_message.tool_calls:
                api_messages.append(response_message)

                for tool_call in response_message.tool_calls:
                    func_name = tool_call.function.name
                    try:
                        args = json.loads(tool_call.function.arguments)
                    except json.JSONDecodeError:
                        args = {}

                    with st.status(f"Executing Tool: {func_name}", expanded=True) as status:
                        st.write("Arguments:", args)

                        if hasattr(toolcalls, func_name):
                            func = getattr(toolcalls, func_name)
                            result = func(**args)
                        else:
                            result = {"status": "error", "error": f"Unknown tool {func_name}"}

                        st.write("Result:", result)
                        status.update(label=f"Tool Execution Completed: {func_name}", state="complete")

                    api_messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(result)
                    })
            else:
                final_text = response_message.content
                response_placeholder.markdown(final_text)
                st.session_state.messages.append({"role": "assistant", "content": final_text})
                break
