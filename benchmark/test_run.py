import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from analysis.sandbox import SandboxRunner
from benchmark.run import (
    _read_json,
    _reference_for_case,
    load_config,
    run_turn,
    validate_schedule,
)
from llm_api.runtime import ToolRuntime
from llm_api.message_utils import serialize_assistant_message


ROOT = Path(__file__).resolve().parents[1]


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.requests.append(kwargs)
        return self.responses.pop(0)


class DumpableCall:
    id = "call-signature"
    type = "function"
    function = SimpleNamespace(name="query_instance_data", arguments='{"paths":["jobs"]}')

    def model_dump(self, exclude_none=True):
        return {"id": self.id, "type": self.type, "function": {"name": self.function.name, "arguments": self.function.arguments}, "extra_content": {"google": {"thought_signature": "opaque"}}}


class DumpableMessage:
    content = ""
    tool_calls = [DumpableCall()]

    def model_dump(self, exclude_none=True):
        return {"role": "assistant", "content": "", "tool_calls": [self.tool_calls[0].model_dump()]}


def response(content="", tool_calls=None):
    message = SimpleNamespace(content=content, tool_calls=tool_calls or [], reasoning_content=None)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=None)


class BenchmarkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config, cls.config_path = load_config(ROOT / "benchmark" / "config.toml")
        cls.base = _read_json(ROOT / "benchmark" / "instances" / "j302_8.json")

    def test_config_validates_and_resolves_paths(self):
        self.assertEqual(self.config["suites"][0]["instance"], "instances/j302_8.json")
        self.assertEqual(self.config["_base_dir"], str(ROOT / "benchmark"))
        self.assertTrue(self.config["_resolved_profile_prompts"][self.config["profiles"][0]["id"]].strip())

    def test_system_prompt_entries_support_file_or_text(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            (directory / "prompt.txt").write_text("A long prompt from disk.\n", encoding="utf-8")
            config_path = directory / "file-prompt.toml"
            config_path.write_text(
                f'''[run]\n\n[[system_prompts]]\nname = "from_file"\nfile = "prompt.txt"\n\n[[system_prompts]]\nname = "inline"\ntxt = "An inline prompt."\n\n[[profiles]]\nid = "named-file"\nendpoint = "http://localhost:1234/v1"\nmodel = "local"\nsystem_prompt = "from_file"\n\n[[profiles]]\nid = "inline-prompt"\nendpoint = "http://localhost:1234/v1"\nmodel = "local"\nsystem_prompt = "inline"\n\n[[suites]]\nid = "one"\ninstance = {str(ROOT / "benchmark" / "instances" / "j302_8.json")!r}\n\n[[suites.cases]]\nid = "one-case"\nprompts = ["hello"]\n''',
                encoding="utf-8",
            )
            config, _ = load_config(config_path)
            self.assertEqual(config["_resolved_profile_prompts"]["named-file"], "A long prompt from disk.\n")
            self.assertEqual(config["_resolved_profile_prompts"]["inline-prompt"], "An inline prompt.")

    def test_provider_tool_metadata_is_preserved(self):
        serialized = serialize_assistant_message(DumpableMessage())
        self.assertEqual(serialized["tool_calls"][0]["extra_content"]["google"]["thought_signature"], "opaque")

    def test_local_sandbox_forwards_json_to_container_stdin(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "candidate.py"
            source.write_text("def analyze(context, parameters): return {}\n", encoding="utf-8")
            completed = SimpleNamespace(
                returncode=0,
                stdout='{"status":"success"}',
                stderr="",
            )
            with patch.dict(os.environ, {"SANDBOX_RUNNER_URL": ""}), patch(
                "analysis.sandbox.subprocess.run", return_value=completed
            ) as run:
                result = SandboxRunner().execute(source, {"instance": {}}, kind="analysis")

            command = run.call_args.args[0]
            payload = json.loads(run.call_args.kwargs["input"])
            self.assertIn("-i", command)
            self.assertEqual(payload["kind"], "analysis")
            self.assertEqual(payload["context"], {"instance": {}})
            self.assertEqual(result["status"], "success")

    def test_runtime_state_isolated_and_does_not_persist(self):
        first = ToolRuntime()
        second = ToolRuntime()
        first.load_instance(self.base)
        second.load_instance(self.base)
        result = first.invoke("set_order_due_date", {"sink_job": 16, "due_date": 40})
        self.assertEqual(result["status"], "success")
        self.assertEqual(first.instance["orders"][0]["due_date"], 40)
        self.assertEqual(second.instance["orders"][0]["due_date"], 18)

    def test_reference_objectives(self):
        expected = {
            "move-order-16-due-date": 62,
            "add-27-before-28": 113,
            "reverse-23-and-4": 114,
            "r1-outage": 98,
            "release-date-via-r5": 106,
        }
        suite = self.config["suites"][0]
        for case in suite["cases"]:
            if case["id"] not in expected:
                continue
            runtime = ToolRuntime()
            runtime.load_instance(self.base)
            instance, _ = _reference_for_case(case, self.config_path.parent, runtime)
            result = runtime.invoke("run_solver", {"time_limit": 5})
            self.assertIn(result["status"], {"optimal", "feasible"})
            check = validate_schedule(instance, runtime.latest_schedule)
            self.assertTrue(check["valid"], check["errors"])
            self.assertEqual(check["objective"], expected[case["id"]])
            if case["id"] == "release-date-via-r5":
                self.assertEqual(check["schedule"][29], (40, 41))

    def test_schedule_validator_rejects_duration_change(self):
        runtime = ToolRuntime()
        runtime.load_instance(self.base)
        runtime.invoke("run_solver", {"time_limit": 5})
        schedule = runtime.latest_schedule
        start, end = schedule["16"] if "16" in schedule else schedule[16]
        schedule["16"] = [start, end + 1]
        check = validate_schedule(self.base, schedule)
        self.assertFalse(check["valid"])
        self.assertTrue(any("duration" in error for error in check["errors"]))

    def test_mocked_tool_round_uses_schema_and_settings(self):
        call = SimpleNamespace(
            id="call-1",
            type="function",
            function=SimpleNamespace(name="set_order_due_date", arguments='{"sink_job":16,"due_date":40}'),
        )
        client = FakeClient([response(tool_calls=[call]), response("done")])
        runtime = ToolRuntime()
        runtime.load_instance(self.base)
        profile = {
            "model": "mock-model",
            "temperature": 0.0,
            "top_p": 1.0,
            "max_tokens": 100,
            "seed": 7,
        }
        history = []
        turn = run_turn(client, profile, runtime, "system", history, "change the due date")
        self.assertIsNone(turn["fatal_error"])
        self.assertEqual(turn["tool_counts"]["set_order_due_date"], 1)
        self.assertEqual(runtime.instance["orders"][0]["due_date"], 40)
        self.assertEqual(client.requests[0]["temperature"], 0.0)
        self.assertEqual(client.requests[0]["seed"], 7)
        self.assertEqual(history[-1]["content"], "done")

    def test_multiple_turns_preserve_compacted_history(self):
        client = FakeClient([response("first"), response("second")])
        runtime = ToolRuntime()
        runtime.load_instance(self.base)
        profile = {"model": "mock-model"}
        history = []
        first = run_turn(client, profile, runtime, "system", history, "first prompt")
        second = run_turn(client, profile, runtime, "system", history, "second prompt")
        self.assertIsNone(first["fatal_error"])
        self.assertIsNone(second["fatal_error"])
        sent = client.requests[1]["messages"]
        self.assertEqual([message["content"] for message in sent[-3:]], ["first prompt", "first", "second prompt"])

    def test_release_case_can_pass_without_a_schedule(self):
        suite = self.config["suites"][0]
        case = next(item for item in suite["cases"] if item["id"] == "unsupported-release-date")
        candidate = ToolRuntime()
        reference = ToolRuntime()
        candidate.load_instance(self.base)
        reference.load_instance(self.base)
        instance, _ = _reference_for_case(case, self.config_path.parent, reference)
        from benchmark.run import evaluate_case
        result = evaluate_case(case, candidate, reference, instance, [{
            "events": [{"type": "assistant", "content": "The release date is not supported."}],
            "fatal_error": None,
            "final_content": "The release date is not supported.",
            "tool_counts": {},
            "successful_mutations": 0,
        }])
        self.assertTrue(result["passed"], result["metrics"])


if __name__ == "__main__":
    unittest.main()
