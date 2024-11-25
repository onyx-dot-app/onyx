import os


def load_env_vars(env_file: str = ".env") -> None:
    current_dir = os.path.dirname(os.path.abspath(__file__))
    env_path = os.path.join(current_dir, env_file)
    try:
        with open(env_path, "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    key, value = line.split("=", 1)
                    os.environ[key] = value.strip()
        print("Successfully loaded environment variables")
    except FileNotFoundError:
        print(f"File {env_file} not found")
