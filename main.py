from graph import build_graph

from collections import Counter


def main():
    graph = build_graph()
    result = graph.invoke({"offers": []})

    kept = [o for o in result["offers"] if o["status"] == "new"]
    top = sorted(kept, key=lambda o: o["score"], reverse=True)[:10]

    print("\nTop 10 offers:")
    for o in top:
        print(f"{o['score']:4d}  {o['title']} @ {o['company']}")
        print(f"      {', '.join(o['reasons'])}")

    rejected = [o for o in result["offers"] if o["status"] == "rejected"]
    reasons = Counter(r for o in rejected for r in o["reasons"])
    print("\nRejection reasons:")
    for reason, count in reasons.most_common():
        print(f"{count:4d}  {reason}")


if __name__ == "__main__":
    main()