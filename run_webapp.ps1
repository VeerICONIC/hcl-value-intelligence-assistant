# Start the Nimbus web app (run from the project folder with the venv activated), then open http://localhost:8000
python -m uvicorn nimbus.api:app --host 127.0.0.1 --port 8000
