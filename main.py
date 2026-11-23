from graph import build_graph


def main():
    graph = build_graph()
    result = graph.invoke({"offers": []})
    print(f"Graph finished with {len(result['offers'])} offers")


if __name__ == "__main__":
    main()