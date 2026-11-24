from collections import Counter

import config
from graph import build_graph


def main():
    graph = build_graph()
    result = graph.invoke({"offers": []})

    new_links = set(result.get("new_links", []))
    new_offers = [o for o in result["offers"] if o["link"] in new_links]
    if not new_offers:
        print("\nNo new offers since last run.")
        return

    kept = [o for o in new_offers if o["status"] == "new"]
    rejected = [o for o in new_offers if o["status"] == "rejected"]
    good = sorted((o for o in kept if o["score"] >= config.MIN_SCORE),
                  key=lambda o: o["score"], reverse=True)

    print(f"\n{len(new_offers)} new offers: {len(good)} above score {config.MIN_SCORE}, "
          f"{len(kept) - len(good)} below, {len(rejected)} rejected")

    for o in good[:config.MAX_DISPLAY]:
        print(f"\n{o['score']:4d}  {o['title']} @ {o['company']}")
        print(f"      {', '.join(o['reasons'])}")
        print(f"      {o['link']}")

    if len(good) > config.MAX_DISPLAY:
        print(f"\n... and {len(good) - config.MAX_DISPLAY} more above score {config.MIN_SCORE}")

    if rejected:
        reasons = Counter(r for o in rejected for r in o["reasons"])
        print("\nRejection reasons: " + ", ".join(f"{r} ({n})" for r, n in reasons.most_common()))


if __name__ == "__main__":
    main()