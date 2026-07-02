import subprocess

def refresh_knowledge_base():

    print("=" * 60)
    print("Refreshing Knowledge Base")
    print("=" * 60)

    subprocess.run(["python", "sync_help_center.py"], check=True)

    subprocess.run(["python", "embed_knowledge_base.py"], check=True)

    print("=" * 60)
    print("Knowledge Base Refresh Complete")
    print("=" * 60)


if __name__ == "__main__":
    refresh_knowledge_base()