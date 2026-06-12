# 1. Navigate to project
cd interview_assistant_pro

# 2. Create virtual environment
python -m venv venv

# Set execution policy to allow scripts
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser

# 3. Activate (Windows)
venv\Scripts\activate

# 4. Activate (macOS/Linux)
source venv/bin/activate

# 5. Run setup (will install dependencies + get API token)
python src/setup.py

# 6. Run the application
python src/main.py