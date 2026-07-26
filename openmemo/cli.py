"""OpenMemo CLI entry point"""
import sys
import asyncio
from .server import run_server
from .tasks import TaskManager, init_db
from .voice import speak, speak_sync
from .conversation import process_message


def main():
    """Main CLI entry point"""
    if len(sys.argv) < 2:
        print("OpenMemo - AI-powered personal voice assistant")
        print()
        print("Usage:")
        print("  openmemo server          Start the server")
        print("  openmemo chat            Interactive chat mode")
        print("  openmemo speak <text>    Speak text aloud")
        print("  openmemo tasks           List pending tasks")
        print("  openmemo init            Initialize database")
        return
    
    command = sys.argv[1]
    
    if command == "server":
        print("Starting OpenMemo server...")
        run_server()
    
    elif command == "chat":
        init_db()
        print("OpenMemo Chat Mode (type 'quit' to exit)")
        print("-" * 40)
        
        while True:
            try:
                user_input = input("You: ").strip()
                if user_input.lower() in ['quit', 'exit', 'q']:
                    print("Goodbye!")
                    break
                if not user_input:
                    continue
                
                reply = asyncio.run(process_message("cli_user", user_input, speak_response=True))
                print(f"OpenMemo: {reply}")
            except (KeyboardInterrupt, EOFError):
                print("\nGoodbye!")
                break
    
    elif command == "speak":
        if len(sys.argv) < 3:
            print("Usage: openmemo speak <text>")
            return
        text = " ".join(sys.argv[2:])
        print(f"Speaking: {text}")
        asyncio.run(speak(text))
    
    elif command == "tasks":
        init_db()
        tm = TaskManager()
        tasks = tm.list_tasks(status="pending")
        if not tasks:
            print("No pending tasks.")
            return
        
        print("Pending Tasks:")
        print("-" * 40)
        for task in tasks:
            time_info = f" @ {task['trigger_time']}" if task['trigger_time'] else ""
            priority = f" [{task['priority']}]" if task['priority'] != 'medium' else ""
            print(f"  {task['task_id']}. {task['content']}{time_info}{priority}")
    
    elif command == "init":
        init_db()
        print("Database initialized.")
    
    else:
        print(f"Unknown command: {command}")
        print("Run 'openmemo' for help.")


if __name__ == "__main__":
    main()
