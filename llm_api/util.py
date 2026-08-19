import copy
import json
import os
import tempfile
import jsonschema
import sys

sys.path.append(os.path.abspath(".."))

from llm_api.schema_validator import (
	validate_instance,
	would_create_cycle,
)

class InvalidPathError(ValueError):
	pass


def _get_path(obj, path):
	if not path or "[" in path or "]" in path:
		raise InvalidPathError(
			"Paths must use dot notation, for example orders.0.due_date."
		)

	current = obj

	for token in path.split("."):
		if isinstance(current, list):
			try:
				current = current[int(token)]
			except (ValueError, IndexError):
				raise InvalidPathError(f"Invalid list index: {token}")

		elif isinstance(current, dict):
			if token not in current:
				raise InvalidPathError(
					f"Key '{token}' does not exist."
				)
			current = current[token]

		else:
			raise InvalidPathError(
				f"Cannot continue through value at '{token}'."
			)

	return current


def _set_path(obj, path, value):
	tokens = path.split(".")
	current = obj

	for token in tokens[:-1]:
		if isinstance(current, list):
			try:
				current = current[int(token)]
			except (ValueError, IndexError):
				raise InvalidPathError(f"Invalid list index: {token}")

		elif isinstance(current, dict):
			if token not in current:
				raise InvalidPathError(
					f"Key '{token}' does not exist."
				)
			current = current[token]

		else:
			raise InvalidPathError(
				f"Cannot continue through '{token}'."
			)

	last = tokens[-1]

	if isinstance(current, list):
		try:
			index = int(last)
			current[index] = value
		except (ValueError, IndexError):
			raise InvalidPathError(f"Invalid list index: {last}")

	elif isinstance(current, dict):
		if last not in current:
			raise InvalidPathError(
				f"Key '{last}' does not exist."
			)
		current[last] = value

	else:
		raise InvalidPathError(
			f"Cannot set value at '{path}'."
		)


def _validate_candidate(candidate):
	try:
		validate_instance(candidate)
		return None
	except (jsonschema.ValidationError, ValueError) as exc:
		return str(exc)


def _atomic_write_json(path, data):
	directory = os.path.dirname(path) or "."

	fd, temporary_path = tempfile.mkstemp(
		dir=directory,
		prefix=".instance-",
		suffix=".json"
	)

	try:
		with os.fdopen(fd, "w", encoding="utf-8") as file:
			json.dump(data, file, indent=2)
			file.write("\n")

		os.replace(temporary_path, path)

	except Exception:
		if os.path.exists(temporary_path):
			os.unlink(temporary_path)
		raise


def _commit_candidate(candidate, description):
	global current_instance

	validation_error = _validate_candidate(candidate)

	if validation_error:
		return {
			"status": "rejected",
			"error_code": "invalid_instance",
			"message": validation_error,
			"instance_modified": False,
		}

	try:
		_atomic_write_json("updated_instance.json", candidate)
	except OSError as exc:
		return {
			"status": "error",
			"error_code": "write_failed",
			"message": str(exc),
			"instance_modified": False,
		}

	current_instance = candidate

	return {
		"status": "success",
		"message": description,
		"instance_modified": True,
	}