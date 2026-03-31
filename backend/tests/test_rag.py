from app.ai.agents.user_story.analysis.tools.rag import get_rag

def test_rag():
    rag = get_rag()

    queries = [
        "user story quality",
        "INVEST principles agile user story quality criteria independent negotiable valuable estimable small testable"
        "Lucassen framework quality",
        "acceptance criteria testability"
    ]

    print("\n================ RAG TEST START ================\n")

    for q in queries:
        print(f"\nQUERY: {q}")

        result = rag.search(q)

        if not result.strip():
            print("No context retrieved")
            continue

        print("\nCONTEXT PREVIEW:\n")
        print(result[:500])

        chunk_count = result.count("\n\n") + 1

        print("\nMETRICS:")
        print(f"- Length: {len(result)} chars")
        print(f"- Chunks approx: {chunk_count}")

        print("\n" + "-" * 60)

    print("\n================ RAG TEST END =================\n")


if __name__ == "__main__":
    test_rag()