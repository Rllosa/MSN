.PHONY: schema

# Regenerate schema/openapi.json from the FastAPI app
schema:
	python scripts/export_openapi.py
