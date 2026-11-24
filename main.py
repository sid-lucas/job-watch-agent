from collections import Counter

from graph import build_graph


def main():
    graph = build_graph()
    result = graph.invoke({"offers": []})

    new_links = set(result.get("new_links", []))
    new_offers = [o for o in result["offers"] if o["link"] in new_links]

    # New offers worth reading, best first
    kept = [o for o in new_offers if o["status"] == "new"]
    if not kept:
        print("\nNo new offers since last run.")
    else:
        print(f"\n{len(kept)} new offers:")
        for o in sorted(kept, key=lambda o: o["score"], reverse=True):
            print(f"{o['score']:4d}  {o['title']} @ {o['company']}")
            print(f"      {', '.join(o['reasons'])}")
            print(f"      {o['link']}")

    # Why the other new offers were rejected
    rejected = [o for o in new_offers if o["status"] == "rejected"]
    if rejected:
        reasons = Counter(r for o in rejected for r in o["reasons"])
        print(f"\n{len(rejected)} new offers rejected:")
        for reason, count in reasons.most_common():
            print(f"{count:4d}  {reason}")


if __name__ == "__main__":
    main()