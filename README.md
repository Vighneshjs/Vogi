# 🤖 Vogi Agentic AI Platform

The Vogi Agentic AI Platform is a local, production-ready developer assistant and vision inspector. It integrates reasoning models (like local Gemma models) with real-world tool execution (files, web browsing, shell execution) and visual code inspection.

---

## ⚡ Quick Start: Automated Launch (Recommended)

The project includes batch and powershell scripts to automate dependency checks, model downloads, server startup, and browser launch.

### 1. Create a Desktop Shortcut
Run this script to create a **Vogi Code Agent** shortcut directly on your desktop:
```bash
Create-Gemma-Desktop-Shortcut.bat
```

### 2. Launch the Application
Double-click the desktop shortcut or run the launcher script from the root folder:
```bash
Start-Gemma-Agent.bat
```
> [!NOTE]
> This launcher automatically checks if **Python** and **Ollama** are installed, downloads missing models (`gemma3:1b` and `gemma4:e4b`), starts the Ollama server if needed, runs the backend, and opens your browser to the platform UI.

---

## 🐍 1. How to Run the Backend (Python FastAPI)

The backend is built using FastAPI and serves both the API endpoints and the static frontend.

### Prerequisites
- **Python 3.10 or higher**
- Ensure Python is added to your environment `PATH`.

### Step 1: Install Python Dependencies
From the project root directory, install all required packages:
```bash
pip install -r requirements.txt
```

### Step 2: Configure Environment Variables (`.env`)
Create or edit the `.env` file in the project root to set your preferences:
```env
# Port on which the FastAPI application will run
PORT=3000

# Choose your LLM provider: 'ollama', 'openai', or 'azure'
VOGI_MODEL_PROVIDER=ollama

# Local Ollama endpoint
OLLAMA_URL=http://127.0.0.1:11434

# Models for the agent and inspection task
VOGI_AGENT_MODEL=gemma3:1b
VOGI_INSPECTION_MODEL=gemma4:e4b

# OpenAI API config (optional, if using OpenAI/Azure provider)
# OPENAI_API_KEY=your-api-key
```

### Step 3: Run the FastAPI Server
Run the application using Uvicorn:
```bash
python -m uvicorn vogi_agent.backend.app:app --host 127.0.0.1 --port 3000 --reload
```
- `--host 127.0.0.1`: Binds the server to localhost.
- `--port 3000`: Runs the application on port `3000`. You can change this port to any desired number.
- `--reload`: Enables hot-reloading for code development (optional).

---

## 🎨 2. How to Serve and Access the Frontend

The frontend is served **directly** by the FastAPI backend. You do not need to start a separate Node.js frontend server.

- **FastAPI Mounts**:
  - The frontend assets are mounted at `/assets`.
  - The main chat/agent interface is served at `/agent` or `/platform`.
  - The home dashboard/HSE dashboard is served at `/`.

### Accessing the UI:
Once the backend server is running, open your web browser and navigate to:
- **Agent Platform (Chat & Tool execution)**: [http://127.0.0.1:3000/agent](http://127.0.0.1:3000/agent)
- **HSE Vision Inspection Dashboard**: [http://127.0.0.1:3000/](http://127.0.0.1:3000/)

> [!TIP]
> If you change the backend port during startup (e.g., `--port 8080`), make sure to adjust the browser URL accordingly (e.g., `http://127.0.0.1:8080/agent`).

---

## 🦙 3. How to Start the Gemma Models (Ollama)

Vogi relies on local models running via **Ollama** for privacy and offline usage.

### Step 1: Start the Ollama Runtime
Make sure the Ollama application is running. You can start it in your terminal or keep it running in the background:
```bash
ollama serve
```

### Step 2: Download the Required Gemma Models
Vogi uses two distinct models: one optimized for **reasoning & tool calls** (Agent Model) and one for **visual inspection** (Inspection Model).
```bash
# Pull the reasoning agent model (Gemma 3 1B)
ollama pull gemma3:1b

# Pull the vision/inspection model (Gemma 4 e4b)
ollama pull gemma4:e4b
```

### Step 3: Verify Installed Models
Confirm that the models were pulled successfully:
```bash
ollama list
```

---

## 🛠️ Troubleshooting & Tips

### 1. Ports Already in Use
If the launcher script detects that port `3088` (or your configured port) is in use, it will automatically increment the port number (e.g., `3089`, `3090`) to find an open port and start the server.

### 2. Missing Python packages on Windows
If you run into issues on Windows while compiling database drivers like `psycopg`, make sure to use the binary package specified in the `requirements.txt`:
```bash
pip install psycopg[binary]
```

### 3. Model Switch via UI
You can switch models (e.g. to Azure GPT-5-mini or other models) directly inside the browser UI on the configuration settings panel. The backend dynamically updates its routing on request.
