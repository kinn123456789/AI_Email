import subprocess


def refresh_classes():

    print("=" * 60)
    print("Refreshing Class Knowledge")
    print("=" * 60)

    subprocess.run(
        ["python", "sync_classes.py"],
        check=True
    )

    subprocess.run(
        ["python", "embed_classes.py"],
        check=True
    )

    print("=" * 60)
    print("Class Knowledge Refresh Complete")
    print("=" * 60)


if __name__ == "__main__":
    refresh_classes()