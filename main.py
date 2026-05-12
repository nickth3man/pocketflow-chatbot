import logging

from dotenv import load_dotenv

from flow import chat_flow
from utils.logging_setup import setup_logging
from utils.shared_builder import build_shared

setup_logging(prefix="cli")
logger = logging.getLogger("nba_chatbot")

load_dotenv()


def main() -> None:
    shared = build_shared(verbose=True)
    print("NBA Basketball Chatbot (CLI)")
    print("Type 'quit' to exit.")
    print()

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if user_input.lower() in ("quit", "exit", "q"):
            break

        if not user_input:
            print("Please enter a question about NBA basketball.")
            continue

        shared["user_message"] = user_input
        shared["step_logs"] = []
        shared["chat_history"].append({
            "role": "user",
            "content": user_input,
            "sql": None,
            "error": False,
        })
        try:
            chat_flow.run(shared)
        except Exception as e:
            logger.error("Flow crashed: %s", e)
            shared["response"] = (
                "Sorry, an unexpected error occurred. Please try rephrasing your question."
            )
        response = shared.get("response", "Sorry, I couldn't generate a response.")

        print("\n── Step Trace ──────────────────────────────")
        for entry in shared.get("step_logs", []):
            icon = "✓" if entry.get("status") == "complete" else "✗"
            print(f"  {icon} [{entry.get('node', '?')}] {entry.get('summary', '')}")
        print("─────────────────────────────────────────────")
        print(f"Bot: {response}")
        print()


if __name__ == "__main__":
    main()
