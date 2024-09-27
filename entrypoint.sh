#!/bin/bash
set -e

# Start Ollama
ollama serve &

# Wait for Ollama to start
sleep 10

# Pull the model
ollama pull llama3.2

# Keep the container running
tail -f /dev/null