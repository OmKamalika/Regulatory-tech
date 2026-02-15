"""
Setup script for Regtech backend.
Run this after creating virtual environment and installing requirements.
"""
import sys
import subprocess
import os
from pathlib import Path


def run_command(command, description):
    """Run a shell command and print status"""
    print(f"\n{'='*60}")
    print(f"  {description}")
    print(f"{'='*60}")

    try:
        result = subprocess.run(
            command,
            shell=True,
            check=True,
            capture_output=True,
            text=True
        )
        print(f"✓ {description} - SUCCESS")
        if result.stdout:
            print(result.stdout)
        return True
    except subprocess.CalledProcessError as e:
        print(f"✗ {description} - FAILED")
        if e.stderr:
            print(f"Error: {e.stderr}")
        return False


def main():
    print("""
╔══════════════════════════════════════════════════════════════╗
║           Regtech Video Compliance - Backend Setup          ║
╚══════════════════════════════════════════════════════════════╝
    """)

    # Check if .env exists
    env_file = Path(".env")
    if not env_file.exists():
        print("⚠ Warning: .env file not found!")
        print("  Copying .env.example to .env...")
        env_example = Path("../.env.example")
        if env_example.exists():
            with open(env_example) as f:
                content = f.read()
            with open(".env", "w") as f:
                f.write(content)
            print("✓ Created .env file")
        else:
            print("✗ .env.example not found. Please create .env manually.")
            return

    # Check Python version
    print(f"\nPython version: {sys.version}")
    if sys.version_info < (3, 10):
        print("⚠ Warning: Python 3.10+ recommended")

    print("\n" + "="*60)
    print("  SETUP STEPS")
    print("="*60)

    steps = [
        ("Check Docker services", "cd ../docker && docker-compose ps"),
        ("Verify database connection", 'python -c "from app.config import settings; print(f\\"Database URL: {settings.DATABASE_URL}\\")"'),
    ]

    for description, command in steps:
        run_command(command, description)

    print("\n" + "="*60)
    print("  NEXT STEPS")
    print("="*60)
    print("""
1. Start Docker services (if not running):
   cd ../docker
   docker-compose up -d

2. Pull Ollama model:
   docker exec -it regtech_ollama ollama pull llama3.1:8b

3. Start the FastAPI server:
   python -m app.main
   # OR
   uvicorn app.main:app --reload

4. Test the API:
   curl http://localhost:8000/health

5. View API documentation:
   Open http://localhost:8000/docs in your browser

6. Run tests:
   pytest tests/ -v
    """)


if __name__ == "__main__":
    main()
