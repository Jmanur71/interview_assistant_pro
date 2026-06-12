"""Setup wizard for Interview Assistant Pro"""

import subprocess
import sys
import os
from token_storage import save_token, load_token


def setup():
    print("=" * 50)
    print("🎯 Interview Assistant Pro - Setup")
    print("=" * 50)

    if sys.version_info < (3, 9):
        print("❌ Python 3.9+ required")
        sys.exit(1)

    print(f"✓ Python {sys.version_info.major}.{sys.version_info.minor} detected")

    print("\n📦 Installing dependencies...")
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "-r", "requirements.txt"],
        check=True
    )

    print("\n🔑 OpenAI API Token Setup")
    print("Get your token from: https://platform.openai.com/api-keys")

    existing = load_token()
    if existing:
        print("✓ Token already configured")
        ans = input("Replace existing token? (y/n): ").lower()
        if ans != "y":
            print("Setup complete!")
            return

    token = input("Enter your OpenAI API token: ").strip()
    if not token:
        print("❌ Token cannot be empty")
        return

    if save_token(token):
        print("✓ Token saved securely in keyring")
    else:
        env_path = os.path.join(os.path.dirname(__file__), "..", "config", ".env")
        with open(env_path, "w") as f:
            f.write(f"OPENAI_API_TOKEN={token}\n")
        print("✓ Token saved to config/.env")

    print("\n✅ Setup complete! Run: python src/main.py")


if __name__ == "__main__":
    setup()