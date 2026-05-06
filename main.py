import os
from console.launcher import launch


def main():
    original_cwd = os.environ.get("ORIGINAL_DIR")
    if original_cwd:
        os.chdir(original_cwd)
    launch()


if __name__ == "__main__":
    main()
