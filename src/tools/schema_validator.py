# tools/schema_validator.py
from typing import Dict, List, Tuple, Any

REQUIRED_FIELDS = [
    "invention_name",
    "technical_description",
    "problem_statement",
    "solution_approach",
    "key_technical_features",
    "domain_classification",
    "statutory_category",
    "inventor_keywords",
    "citations",
]

def validate_schema(obj: Dict[str, Any]) -> Tuple[bool, List[str]]:
    errors = []
    if not isinstance(obj, dict):
        return False, ["Output is not a JSON object"]

    for f in REQUIRED_FIELDS:
        if f not in obj:
            errors.append(f"Missing field: {f}")
        else:
            v = obj[f]
            if v is None:
                errors.append(f"Empty field: {f}")
            elif isinstance(v, str) and len(v.strip()) == 0:
                errors.append(f"Empty string field: {f}")

    if "key_technical_features" in obj and not isinstance(obj["key_technical_features"], list):
        errors.append("key_technical_features must be a list")

    if "inventor_keywords" in obj and not isinstance(obj["inventor_keywords"], list):
        errors.append("inventor_keywords must be a list")

    # citations must be dict of field -> list of chunk_ids
    if "citations" in obj:
        if not isinstance(obj["citations"], dict):
            errors.append("citations must be a dict")
        else:
            if len(obj["citations"]) == 0:
                errors.append("citations must not be empty")
            for field, ids in obj["citations"].items():
                if not isinstance(ids, list):
                    errors.append(f"citations[{field}] must be a list")
                elif len(ids) == 0:
                    errors.append(f"citations[{field}] must not be empty")
                else:
                    for x in ids:
                        if not isinstance(x, str) or len(x.strip()) == 0:
                            errors.append(f"citations[{field}] contains invalid chunk id")

    return (len(errors) == 0), errors